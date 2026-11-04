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
from modules.diagnostics import record_failure as _record_failure



def _permission_decision(owner, name, target):
    try:
        from modules import permission_audit, permission_classify, permission_gate, permission_policy, service_store
        service_store.identity(owner)
        kind, recognized = permission_classify.classify_detail('file', name, target)
        if not recognized:
            kind = 'local_reversible'  # Mevcut işlemler çakışmasız ve geri alınabilir.
        result = permission_gate.decide({'class': kind, 'target': target, 'via': 'file'})
        decision, reason = permission_policy.apply(owner, 'file', kind, result['decision'], result['reason'])
        if decision not in ('allow', 'ask', 'deny'):
            raise ValueError('Geçersiz izin kararı.')
        permission_audit.record(owner, decision, kind, target, 'file', reason)
        return None if decision == 'allow' else reason
    except Exception:
        _record_failure('modules/file_ops.py:permission_gate')
        return 'İzin denetimi tamamlanamadı; dosya işlemi yapılmadı.'


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
    if reason := _permission_decision(owner, 'Taşı', str(source)):
        return reason
    try:
        final = files._free_name(folder / source.name)
        shutil.move(str(source), str(final))
    except OSError as exc:
        return f"Dosyayı taşıyamadım: {exc}"
    _record([[str(final), str(source), _digest(final)]], owner)
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
    if reason := _permission_decision(owner, 'Yeniden adlandır', str(source)):
        return reason
    try:
        source.rename(target)
    except OSError as exc:
        return f"Adı değiştiremedim: {exc}"
    _record([[str(target), str(source), _digest(target)]], owner)
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
    if reason := _permission_decision(owner, 'Metin dosyası oluştur', str(folder / name)):
        return reason
    try:
        final = files._free_name(folder / name)
        final.write_text(content + ("\n" if content else ""), encoding="utf-8")
    except OSError as exc:
        return f"Dosyayı oluşturamadım: {exc}"
    _record([[str(final), "", _digest(final)]], owner)
    return (f"{label} klasöründe {final.name} dosyasını oluşturdum" + (" ve içine yazdım." if content else ".")
            + " İstersen “son dosya işlemini geri al” de.")


def undo(owner: str = "") -> str:
    from modules import llm
    owner = owner or llm._key_context.get() or ''
    if reason := _permission_decision(owner, 'Geri al', 'Son dosya işlemi'):
        return reason
    try:
        pairs = json.loads(_undo_path(owner).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "Geri alınacak bir dosya işlemi yok."
    done = 0
    pending = []
    for entry in reversed(pairs):
        new, old = entry[0], entry[1]
        try:
            if not os.path.exists(new):
                pending.append(entry)
                continue
            if old == "":
                # Oluşturulan dosya yalnız Jarvis'in yazdığı içerikle aynıysa silinir.
                if len(entry) > 2 and _digest(Path(new)) == entry[2]:
                    os.remove(new)
                    done += 1
                else:
                    pending.append(entry)
            elif len(entry) > 2 and _digest(Path(new)) != entry[2]:
                # Taşınan/yeniden adlandırılan dosya sonradan değiştirildiyse kimliğini koru.
                pending.append(entry)
            elif os.path.exists(old):
                # Eski konum doluysa üzerine yazma; kayıt sonraki deneme için kalsın.
                pending.append(entry)
            else:
                shutil.move(new, old)
                done += 1
        except OSError:
            pending.append(entry)
    try:
        if pending:
            _record(list(reversed(pending)), owner)
        else:
            _undo_path(owner).unlink(missing_ok=True)
    except OSError:
        pass
    if done and not pending:
        return "Son dosya işlemini geri aldım."
    if done and pending:
        return "Geri alma kısmen tamamlandı; engellenen kayıtları daha sonra yeniden deneyebilirsin."
    return "Son dosya işlemini geri alamadım (dosya değişmiş, yerinde değil ya da eski konum dolu); dosyana dokunmadım."


def execute_typed(operation: str, *, owner: str = "", path: str = "",
                  folder: str = "", name: str = "", content: str = "") -> str:
    """Execute a Brain/Core-validated file mutation; never parses natural language."""
    if operation == "undo":
        return undo(owner)
    if operation not in {"move", "rename", "create"}:
        return "Dosya işlemi türü doğrulanamadı; işlem başlatılmadı."
    if operation in {"move", "rename"}:
        if not isinstance(path, str) or not path or "\\x00" in path or len(path) > 4096:
            return "Dosya yolu doğrulanamadı; işlem başlatılmadı."
        source = Path(path)
        try:
            roots = [root.resolve() for root in _roots()]
            if source.is_symlink() or not source.is_file() or source.parent.resolve() not in roots:
                return "Dosya artık izinli konumda değil; işlem başlatılmadı."
        except OSError:
            return "Dosya konumu doğrulanamadı; işlem başlatılmadı."
        if operation == "move":
            hit = files.match_folder(_fold(folder))
            if not hit or hit[1] not in _DEST:
                return "Hedef klasör doğrulanamadı; işlem başlatılmadı."
            destination, label, _need = hit
            if source.parent.resolve() == destination.resolve():
                return f"{source.name} zaten {label} klasöründe."
            if reason := _permission_decision(owner, "Taşı", str(source)):
                return reason
            try:
                target = files._free_name(destination / source.name)
                shutil.move(str(source), str(target))
                _record([[str(target), str(source), _digest(target)]], owner)
            except OSError:
                return "Dosyayı güvenli biçimde taşıyamadım."
            return f"{source.name} dosyasını {label} klasörüne taşıdım."
        new, problem = _valid_name(name, source)
        if not new:
            return problem
        target = source.with_name(new)
        if target.exists() and target.resolve() != source.resolve():
            return f"{new} adında bir dosya zaten var; üzerine yazmadım."
        if reason := _permission_decision(owner, "Yeniden adlandır", str(source)):
            return reason
        try:
            source.rename(target)
            _record([[str(target), str(source), _digest(target)]], owner)
        except OSError:
            return "Dosyanın adını güvenli biçimde değiştiremedim."
        return f"{source.name} dosyasının adını {new} yaptım."
    hit = files.match_folder(_fold(folder))
    if not hit or hit[1] not in ("Masaüstü", "İndirilenler", "Belgeler"):
        return "Hedef klasör doğrulanamadı; işlem başlatılmadı."
    destination, label, _need = hit
    if not isinstance(name, str) or not name.strip() or len(name) > 120 or not isinstance(content, str) or len(content) > 16000 or "\\x00" in content:
        return "Dosya adı veya içeriği doğrulanamadı; işlem başlatılmadı."
    filename, problem = _valid_name(name, Path("x.txt"))
    if not filename:
        return problem
    if Path(filename).suffix.lower() != ".txt":
        filename = Path(filename).stem + ".txt"
    if reason := _permission_decision(owner, "Metin dosyası oluştur", str(destination / filename)):
        return reason
    try:
        target = files._free_name(destination / filename)
        target.write_text(content + ("\\n" if content else ""), encoding="utf-8", errors="strict")
        _record([[str(target), "", _digest(target)]], owner)
    except OSError:
        return "Metin dosyasını güvenli biçimde oluşturamadım."
    return f"{label} klasöründe {target.name} dosyasını oluşturdum."


def handle(command: str, owner: str = "") -> str | None:
    """“rapor.pdf dosyasını belgelere taşı”, “x dosyasının adını y yap”, “masaüstüne not adında bir metin dosyası oluştur
    ve içine merhaba yaz”, “son dosya işlemini geri al”. İlgisizse None."""
    from modules import llm
    owner = owner or llm._key_context.get() or ''
    if re.search(r"\bson dosya işlemi\w*\s+geri\s+al", _fold(command)):
        return undo(owner)
    for fn in (_move, _rename, _create):
        reply = fn(command, owner)
        if reply is not None:
            return reply
    return None
