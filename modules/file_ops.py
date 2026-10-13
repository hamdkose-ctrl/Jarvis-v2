"""Tek dosya işlemleri: taşı, yeniden adlandır, metin dosyası oluştur, geri al.

Yalnız kullanıcının bilinen klasörlerinde (Masaüstü, İndirilenler, Belgeler, Resimler, Jarvis Dosyaları), alt klasörlere
inmeden çalışır. Silme ve üzerine yazma yoktur; her işlem geri alınabilir olduğu için onay istemez.
"""
from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

from config import DATA_DIR
from modules import files



def _undo_path(owner: str = "") -> Path:
    """Geri alma kaydı kullanıcıya özeldir: başka kullanıcının son işlemi geri alınamaz."""
    return DATA_DIR / ("file_op_undo_" + (re.sub(r"[^\w-]", "_", owner)[:60] or "ortak") + ".json")


def _digest(path: Path) -> str:
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()
_BAD_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
_DEST = ("Masaüstü", "İndirilenler", "Belgeler", "Resimler")


def _fold(text: str) -> str:
    return text.replace("İ", "i").replace("I", "ı").lower()


def _roots() -> list[Path]:
    out = []
    for _pattern, candidates, _need, _label in files._FOLDERS:
        folder = files.folder_path(candidates)
        if folder:
            out.append(folder)
    shared = Path.home() / "Documents" / "Jarvis Dosyaları"
    if shared.is_dir():
        out.append(shared)
    return out


def _clean(text: str) -> str:
    return text.strip().strip("\"'“”‘’").strip()


def _find(name: str, only: Path | None = None) -> list[Path]:
    """Ada (uzantılı ya da uzantısız, Türkçe ekli ya da eksiz) göre dosya arar."""
    wanted = _fold(_clean(name))
    variants = [wanted]
    trimmed = re.sub(r"['’]?(?:y?[ıiuü]|n[ıiuü])$", "", wanted).strip(" '’")
    if trimmed and trimmed != wanted:
        variants.append(trimmed)
    for variant in variants:
        hits = []
        for folder in _roots():
            if only and folder.resolve() != only.resolve():
                continue
            hits += [f for f in files._real_files(folder) if not f.is_symlink() and (_fold(f.name) == variant or _fold(f.stem) == variant)]
        if hits:
            return list({h.resolve(): h for h in hits}.values())
    return []


def _source(words: list[str]) -> tuple[list[str], Path | None]:
    """Baştaki “indirilenlerdeki” sözcüğünü kaynak klasör yapar, sondaki “dosyasını” sözcüğünü atar."""
    only = None
    if words and re.search(r"(?:daki|deki|taki|teki)$", _fold(words[0])):
        hit = files.match_folder(_fold(words[0]))
        if hit:
            only, words = hit[0], words[1:]
    while words and re.fullmatch(r"dosya\w*", _fold(words[-1])):
        words = words[:-1]
    return words, only


def _choices(hits: list[Path]) -> str:
    return "; ".join(f"{h.name} ({h.parent.name})" for h in hits[:5])


def _record(pairs: list[list[str]], owner: str = "") -> None:
    _undo_path(owner).write_text(json.dumps(pairs, ensure_ascii=False), encoding="utf-8")


def _valid_name(new: str, old: Path) -> tuple[str | None, str]:
    new = _clean(new)
    if not new or len(new) > 120 or _BAD_NAME.search(new) or new.endswith((" ", ".")):
        return None, "Yeni ad geçersiz; \\ / : * ? \" < > | karakterleri kullanılamaz."
    if not Path(new).suffix:
        new += old.suffix
    if Path(new).stem.lower() in _RESERVED:
        return None, "Bu ad Windows'ta ayrılmış, başka bir ad söyle."
    return new, ""


def _move(command: str, owner: str = "") -> str | None:
    found = re.match(r"^(?:lütfen\s+)?(.+?)\s+taşı\w*(?:\s+(?:mısın|misin))?[ .!?]*$", command.strip(), re.I)
    if not found:
        return None
    words = found.group(1).split()
    destination = None
    for n in (1, 2):
        if len(words) > n:
            tail = _fold(" ".join(words[-n:]))
            hit = files.match_folder(tail)
            if hit and hit[1] in _DEST and (n == 1 or "klasör" in tail):
                destination, words = hit, words[:-n]
                break
    if not destination:
        return None
    words, only = _source(words)
    if not words:
        return "Hangi dosyayı taşıyayım?"
    hits = _find(" ".join(words), only)
    if not hits:
        return f"“{_clean(' '.join(words))[:60]}” adında bir dosya bulamadım (Masaüstü, İndirilenler, Belgeler, Resimler ve Jarvis Dosyaları klasörlerine baktım)."
    if len(hits) > 1:
        return "Birden fazla dosya var, hangisi? " + _choices(hits)
    source, (folder, label, _need) = hits[0], destination
    if source.parent.resolve() == folder.resolve():
        return f"{source.name} zaten {label} klasöründe."
    try:
        final = files._free_name(folder / source.name)
        shutil.move(str(source), str(final))
    except OSError as exc:
        return f"Dosyayı taşıyamadım: {exc}"
    _record([[str(final), str(source)]], owner)
    return f"{source.name} dosyasını {label} klasörüne taşıdım. İstersen “son dosya işlemini geri al” de."


def _rename(command: str, owner: str = "") -> str | None:
    found = re.match(
        r"^(?:lütfen\s+)?(.+?)\s+(?:dosyas[ıi]n[ıi]n?\s+ad[ıi]n[ıi]|dosyay[ıi]|dosyas[ıi]n[ıi]|ad[ıi]n[ıi])\s+(.+?)\s+"
        r"(?:olarak\s+(?:de[ğg]i[sş]tir\w*|yeniden\s+adland[ıi]r\w*)|yap(?:ar m[ıi]s[ıi]n)?|yeniden\s+adland[ıi]r\w*)[ .!?]*$",
        command.strip(), re.I)
    if not found:
        return None
    words, only = _source(found.group(1).split())
    if not words:
        return "Hangi dosyanın adını değiştireyim?"
    hits = _find(" ".join(words), only)
    if not hits:
        return f"“{_clean(' '.join(words))[:60]}” adında bir dosya bulamadım."
    if len(hits) > 1:
        return "Birden fazla dosya var, hangisi? " + _choices(hits)
    source = hits[0]
    new, problem = _valid_name(found.group(2), source)
    if not new:
        return problem
    target = source.with_name(new)
    if target.exists() and _fold(target.name) != _fold(source.name):
        return f"{new} adında bir dosya zaten var; üzerine yazmadım."
    try:
        source.rename(target)
    except OSError as exc:
        return f"Adı değiştiremedim: {exc}"
    _record([[str(target), str(source)]], owner)
    return f"{source.name} dosyasının adını {new} yaptım. İstersen “son dosya işlemini geri al” de."


def _create(command: str, owner: str = "") -> str | None:
    found = re.match(
        r"^(?:lütfen\s+)?(\S+)\s+(?:klasörüne\s+)?(.+?)\s+(?:ad[ıi]nda|adl[ıi]|isimli)\s+(?:bir\s+)?(?:metin|not|txt)\s+dosyas[ıi]\s+"
        r"(?:olu[sş]tur\w*|yap\w*)(?:\s+(?:ve\s+)?i[çc]ine\s+(.+?)\s+yaz\w*)?[ .!?]*$", command.strip(), re.I)
    if not found:
        return None
    hit = files.match_folder(_fold(found.group(1)))
    if not hit or hit[1] not in ("Masaüstü", "İndirilenler", "Belgeler"):
        return None
    folder, label, _need = hit
    name, problem = _valid_name(found.group(2), Path("x.txt"))
    if not name:
        return problem
    if Path(name).suffix.lower() != ".txt":
        name = Path(name).stem + ".txt"
    content = _clean(found.group(3) or "")
    try:
        final = files._free_name(folder / name)
        final.write_text(content + ("\n" if content else ""), encoding="utf-8")
    except OSError as exc:
        return f"Dosyayı oluşturamadım: {exc}"
    _record([[str(final), "", _digest(final)]], owner)
    return (f"{label} klasöründe {final.name} dosyasını oluşturdum" + (" ve içine yazdım." if content else ".")
            + " İstersen “son dosya işlemini geri al” de.")


def undo(owner: str = "") -> str:
    try:
        pairs = json.loads(_undo_path(owner).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "Geri alınacak bir dosya işlemi yok."
    done = 0
    for entry in reversed(pairs):
        new, old = entry[0], entry[1]
        try:
            if not os.path.exists(new):
                continue
            if old == "":
                # Oluşturulan metin dosyası yalnız Jarvis'in yazdığı içerikle aynıysa silinir; sonradan düzenlendiyse dokunulmaz.
                if len(entry) > 2 and _digest(Path(new)) == entry[2]:
                    os.remove(new)
                    done += 1
            elif not os.path.exists(old):
                shutil.move(new, old)
                done += 1
        except OSError:
            continue
    try:
        _undo_path(owner).unlink()
    except OSError:
        pass
    return "Son dosya işlemini geri aldım." if done else "Son dosya işlemini geri alamadım (dosya değişmiş ya da yerinde değil); dosyana dokunmadım."


def handle(command: str, owner: str = "") -> str | None:
    """“rapor.pdf dosyasını belgelere taşı”, “x dosyasının adını y yap”, “masaüstüne not adında bir metin dosyası oluştur
    ve içine merhaba yaz”, “son dosya işlemini geri al”. İlgisizse None."""
    if re.search(r"\bson dosya işlemi\w*\s+geri\s+al", _fold(command)):
        return undo(owner)
    for fn in (_move, _rename, _create):
        reply = fn(command, owner)
        if reply is not None:
            return reply
    return None
