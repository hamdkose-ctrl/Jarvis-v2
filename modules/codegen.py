"""1) Kod üretimi: kod bloğu + dosyaya yazma."""
import re
from pathlib import Path
from .llm import ask
from . import persona

# Karar 3: math/notation cümlesinin tek sahibi persona; kod bloğu ve not uzunluğu
# ise bu yapının (_extract) çıktı şemasıdır.
SYSTEM = ("Sen kıdemli bir yazılım mühendisisin. Yalnızca çalışır, yorumlu ve tip belirteçli kod üret. "
          "Kodu tek bir ```dil bloğunda ver (örn. ```python). Kodun önüne tek cümlelik giriş, "
          "arkasına en fazla 3 cümlelik kullanım notu ekle. Türkçe yaz. " + persona.notation_text('düz'))

def _extract(text: str) -> str:
    m = re.search(r"```(?:\w+)?\n(.*?)```", text, re.S)
    return m.group(1) if m else text

def generate(task: str, language: str = "python") -> str:
    """Kod bloğu (```dil ... ```) ve kısa açıklama döndürür; arayüz bloğu kopyalanabilir panel olarak gösterir."""
    text = ask(f"Dil: {language}\nGörev: {task}", SYSTEM, max_tokens=4000).strip()
    if "```" not in text:   # model bloğu unuttuysa sar
        text = f"```{language}\n{text}\n```"
    return text

def save(code: str, path: str) -> Path:
    p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(code, encoding="utf-8"); return p
