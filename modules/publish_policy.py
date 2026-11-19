"""Yayın ve güncellemenin ortak kaynak dosya politikası; yerel çıktılar dışarıda kalır."""
import fnmatch
from pathlib import Path

ALLOWED_EXTENSIONS = {".py", ".js", ".html", ".css", ".md", ".txt", ".json", ".bat", ".toml", ".yaml", ".yml", ".java", ".gradle", ".properties", ".xml", ".svg", ".png", ".jpg", ".jpeg", ".webp", ".woff2", ".ico", ".jar"}
SKIP_PARTS = {".venv_install", ".venv_backup", ".jarvis", ".claude", "models", ".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", "backups", ".backups", ".gradle", "build", ".idea", "tmp"}
SKIP_NAMES = {".env", "settings.json", "gemini_key.txt", "groq_key.txt", "github_token.txt", "phone_token.txt", "local.properties", "chat_sessions.json", "requests.json"}
LOCAL_ONLY_PARTS = {".v2_kontrol_gecici", ".ruff_cache", ".claude-mem", "JarvisAndroid"}
LOCAL_ONLY_NAMES = ("v2_kabul_sonucu*.json", "*.yeni")


def is_publishable_path(rel: str) -> bool:
    pp = Path(rel)
    return (not any(fnmatch.fnmatch(pp.name, pattern) for pattern in LOCAL_ONLY_NAMES)
            and not any(part in LOCAL_ONLY_PARTS | SKIP_PARTS for part in pp.parts)
            and pp.name not in SKIP_NAMES and not pp.name.startswith(".env.")
            and (pp.suffix.lower() in ALLOWED_EXTENSIONS
                 or pp.name in {".gitignore", ".gitattributes"}
                 or pp.as_posix() == "modules/desktop_uia.ps1"))

