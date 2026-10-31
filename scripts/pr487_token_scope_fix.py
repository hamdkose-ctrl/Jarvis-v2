from pathlib import Path

p = Path('modules/brain_understanding.py')
text = p.read_text(encoding='utf-8')
old = '''    "sil",\n    "düzelt",\n    "duzelt",\n    "değiştir",\n    "degistir",\n    "güncelle",\n    "guncelle",\n    "gönder",'''
new = '''    "sil",\n    "gönder",'''
if text.count(old) != 1:
    raise SystemExit(f'global note-mutation token bloğu beklenen gibi değil: {text.count(old)}')
p.write_text(text.replace(old, new), encoding='utf-8')

Path('.github/workflows/pr487-token-scope-fix.yml').unlink(missing_ok=True)
Path('scripts/pr487_token_scope_fix.py').unlink(missing_ok=True)
