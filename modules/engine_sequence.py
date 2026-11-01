"""engine sequence; all mutable dependencies are supplied by EngineContext."""
from __future__ import annotations

def _split_steps(runtime, command: str) -> list[str] | None:
    """'önce A, sonra B' / 'A ardından B' -> [A, B]. Tek adımlıysa None. En fazla 5 adım."""
    text = runtime.re.sub(r"^\s*önce\s+", "", command, flags=runtime.re.I)
    if text == command and not runtime.re.search(r"\s(?:ardından|akabinde)\s", command, runtime.re.I) \
            and not runtime.re.search(r"\bönce\b.+\bsonra\b", command, runtime.re.I):
        return None
    parts = [x.strip(" ,.") for x in runtime._STEP_SPLIT.split(text)]
    parts = [x for x in parts if len(x) >= 3]
    return parts[:5] if len(parts) >= 2 else None

def _run_steps(runtime, steps: list[str]) -> str:
    """Çok adımlı cümlenin TEK canonical kararı vardır; adım metni ikinci kez yorumlanmaz.

    Adımlar ikinci bir yorumlama/resolver zincirine gönderilmez, hiçbir effect çalışmaz.
    Her adım kendi turn'ünde tek bir canonical karar alabilsin diye adımlar kullanıcıya
    sırayla gösterilir; eksik bilgi uydurulmaz."""
    joined = [str(st) for st in steps]
    runtime.privacy.audit("çok adımlı komut", f"{len(joined)} adım")
    return ("Bu isteği tek bir canonical karar olarak yorumladım; adımları ikinci kez kendim "
            "yorumlayıp sırayla çalıştırmam. Adımları tek tek söyle:\n"
            + "\n".join(f"{i}. {st}" for i, st in enumerate(joined, 1)))

def _close_jarvis(runtime):
    runtime.flags['closing'] = True
    runtime.emit("activity", "Jarvis kapatma istendi", "working|Jarvis|Yalnızca Jarvis uygulaması kapanacak; bilgisayar açık kalacak.")
    runtime.threading.Timer(1.8, runtime.stop_event.set).start()
    return "Jarvis'i kapatıyorum. Bilgisayar açık kalacak."
