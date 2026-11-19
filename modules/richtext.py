"""Yanıt metnini düz metin ve kod bloklarına ayırır (arayüz ve sesli okuma için)."""
from __future__ import annotations

import re

_FENCE = re.compile(r"```[ \t]*([\w+#.-]*)[ \t]*\n(.*?)(?:```|\Z)", re.S)

EXTENSIONS = {"python": ".py", "py": ".py", "javascript": ".js", "js": ".js", "typescript": ".ts", "ts": ".ts",
              "html": ".html", "css": ".css", "json": ".json", "bash": ".sh", "sh": ".sh", "powershell": ".ps1",
              "ps1": ".ps1", "java": ".java", "c": ".c", "cpp": ".cpp", "c++": ".cpp", "csharp": ".cs", "cs": ".cs",
              "go": ".go", "rust": ".rs", "sql": ".sql", "php": ".php", "ruby": ".rb", "kotlin": ".kt",
              "swift": ".swift", "yaml": ".yml", "xml": ".xml", "markdown": ".md"}


def split_blocks(text: str) -> list[tuple[str, str, str]]:
    """[('text', '', metin) | ('code', dil, kod), ...] — kapanmamış ``` bloğu sonuna kadar kod sayılır."""
    parts: list[tuple[str, str, str]] = []
    pos = 0
    for m in _FENCE.finditer(text):
        before = text[pos:m.start()].strip("\n")
        if before.strip():
            parts.append(("text", "", before.strip()))
        parts.append(("code", (m.group(1) or "").lower(), m.group(2).strip("\n")))
        pos = m.end()
    rest = text[pos:].strip()
    if rest:
        parts.append(("text", "", rest))
    return parts or [("text", "", text)]


def has_code(text: str) -> bool:
    return "```" in text


def speakable(text: str) -> str:
    """Sesli okuma için: kod bloklarını okumaz, işaretleri temizler."""
    code = has_code(text)
    plain = " ".join(t for kind, _lang, t in split_blocks(text) if kind == "text") if code else text
    plain = re.sub(r"[*`#_]{1,3}", "", plain).strip()
    if code:
        plain = (plain + " Kodu sohbet ekranına yazdım.").strip()
    return plain


def extension(lang: str) -> str:
    return EXTENSIONS.get((lang or "").lower(), ".txt")


# ---- LaTeX → düz metin / Unicode (kod blokları hariç) ----
_SYMBOLS = {r"\pm": "±", r"\mp": "∓", r"\times": "×", r"\cdot": "·", r"\div": "÷", r"\leq": "≤", r"\le": "≤",
            r"\geq": "≥", r"\ge": "≥", r"\neq": "≠", r"\ne": "≠", r"\approx": "≈", r"\equiv": "≡",
            r"\infty": "∞", r"\rightarrow": "→", r"\to": "→", r"\leftarrow": "←", r"\Rightarrow": "⇒",
            r"\Leftrightarrow": "⇔", r"\in": "∈", r"\notin": "∉", r"\subset": "⊂", r"\cup": "∪", r"\cap": "∩",
            r"\sum": "∑", r"\prod": "∏", r"\int": "∫", r"\pi": "π", r"\alpha": "α", r"\beta": "β",
            r"\gamma": "γ", r"\delta": "δ", r"\theta": "θ", r"\lambda": "λ", r"\mu": "μ", r"\sigma": "σ",
            r"\omega": "ω", r"\Delta": "Δ", r"\degree": "°", r"\circ": "°", r"\ldots": "…", r"\dots": "…",
            r"\%": "%", r"\_": "_", r"\&": "&", r"\#": "#", r"\$": "$", r"\,": " ", r"\;": " ", r"\!": "",
            r"\quad": " ", r"\ ": " "}
_SUPER = str.maketrans("0123456789+-=()n", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿ")
_SUB = str.maketrans("0123456789+-=()", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎")
_BARE = re.compile(r"\\(?:frac|dfrac|sqrt|text|mathrm|pm|times|cdot|leq|geq|neq|infty|rightarrow|sum)\b")
_MATHY = re.compile(r"\\[A-Za-z]|\^|_\{|\{|\\\(|\\\[")


def _brace(text: str, start: int) -> tuple[str, int] | None:
    """text[start] == '{' ise eşleşen '}' içindeki metni ve bitiş konumunu döndürür."""
    if start >= len(text) or text[start] != "{":
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1:i], i + 1
    return None


def _group(s: str) -> str:
    s = s.strip()
    return s if re.fullmatch(r"[\w.,]+", s) else f"({s})"


def _latex(expr: str, generic: bool = True) -> str:
    s = expr
    for _ in range(4):   # iç içe \frac, \sqrt için birkaç tur
        out, i, changed = [], 0, False
        while i < len(s):
            m = re.match(r"\\(frac|dfrac|tfrac)(?=\{)", s[i:])
            if m:
                a = _brace(s, i + m.end())
                b = _brace(s, a[1]) if a else None
                if a and b:
                    out.append(f"{_group(_latex(a[0]))}/{_group(_latex(b[0]))}")
                    i, changed = b[1], True
                    continue
            m = re.match(r"\\sqrt(?:\[(\w+)\])?(?=\{)", s[i:])
            if m:
                a = _brace(s, i + m.end())
                if a:
                    root = {"3": "∛", "4": "∜"}.get(m.group(1) or "", "√")
                    out.append(f"{root}{_group(_latex(a[0]))}")
                    i, changed = a[1], True
                    continue
            m = re.match(r"\\(?:text|mathrm|mathbf|mathit|textbf|operatorname|boldsymbol)(?=\{)", s[i:])
            if m:
                a = _brace(s, i + m.end())
                if a:
                    out.append(a[0])
                    i, changed = a[1], True
                    continue
            out.append(s[i])
            i += 1
        s = "".join(out)
        if not changed:
            break
    s = re.sub(r"\\(?:left|right|big|Big|bigg|Bigg)\b\s*", "", s)
    for cmd in sorted(_SYMBOLS, key=len, reverse=True):
        s = s.replace(cmd, _SYMBOLS[cmd])
    # üst ve alt simgeler
    s = re.sub(r"\^\{([^{}]*)\}", lambda m: m.group(1).translate(_SUPER) if set(m.group(1)) <= set("0123456789+-=()n") else f"^({m.group(1)})", s)
    s = re.sub(r"\^([0-9n])", lambda m: m.group(1).translate(_SUPER), s)
    s = re.sub(r"_\{([^{}]*)\}", lambda m: m.group(1).translate(_SUB) if set(m.group(1)) <= set("0123456789+-=()") else f"_{m.group(1)}", s)
    s = re.sub(r"_([0-9])", lambda m: m.group(1).translate(_SUB), s)
    if generic:
        s = re.sub(r"\\([A-Za-z]+)", r"\1", s)   # tanınmayan \komut → komut adı
    return s.replace("{", "").replace("}", "")


def _clean_text(text: str) -> str:
    text = re.sub(r"\\\[(.+?)\\\]|\\\((.+?)\\\)", lambda m: _latex(m.group(1) or m.group(2)), text, flags=re.S)

    def dollars(m: re.Match) -> str:
        inner = m.group(1) or m.group(2)
        # yalnızca gerçekten matematik gibi görünenler: para tutarları ($100 ve $200) bozulmasın
        return _latex(inner.strip()) if _MATHY.search(inner) else m.group(0)

    text = re.sub(r"\$\$(.+?)\$\$|\$([^$\n]+?)\$", dollars, text, flags=re.S)
    if _BARE.search(text):   # $ işaretsiz yazılmış bilinen LaTeX komutları (dosya yollarındaki \ işaretine dokunmaz)
        text = _latex(text, generic=False)
    return text


def clean_math(text: str) -> str:
    """LaTeX işaretlerini okunur düz metne çevirir; ``` kod blokları değişmez."""
    if "\\" not in text and "$" not in text and "^" not in text:
        return text
    out = []
    for kind, lang, chunk in split_blocks(text):
        out.append(f"```{lang}\n{chunk}\n```" if kind == "code" else _clean_text(chunk))
    return "\n".join(out)
