#!/usr/bin/env bash
# Jarvis Linux test ortamı (bulut/CI). Windows kurulumu kurulum.bat ile yapılır; bu betik ona dokunmaz.
# Kilit dosyası değiştirilmez: yalnız Windows'a özgü paketler atlanır, kalan sabit sürümler aynen kurulur.
# Kullanım: bash scripts/linux_test_kurulum.sh [--test] [venv_klasörü]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_TESTS=0
if [ "${1:-}" = "--test" ]; then RUN_TESTS=1; shift; fi
VENV="${1:-$ROOT/.venv}"
PY="${PYTHON:-python3}"
LOCK="$ROOT/requirements.lock.txt"
# Yalnız Windows'ta bulunan paketler (Linux'ta pip'te yok ya da Windows API ister).
WINDOWS_ONLY="comtypes pycaw pypiwin32 pywin32 wmi"
# Kilitteki pystray/pyautogui'nin yalnız Linux'ta istediği dolaylı bağımlılıklar (Windows kilidinde yoklar).
LINUX_EXTRA="python-xlib==0.33 python3-xlib==0.15"
# Kilitteki paketlerin Linux'ta bulunmayan, yalnız gerçek çalışmada gereken alt bağımlılıkları.
# openwakeword Linux'ta tflite-runtime ister; testler onnxruntime ile yetinir ve modeli yüklemez.
KNOWN_MISSING="tflite-runtime"

if [ "$(uname -s)" != "Linux" ]; then
    echo "Bu betik yalnız Linux içindir. Windows'ta scripts/kurulum.bat kullanılır." >&2; exit 2
fi
if [ -d "$VENV/Scripts" ]; then
    echo "$VENV bir Windows ortamı; dokunulmadı. Başka bir klasör ver." >&2; exit 2
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "[1/5] Sanal ortam: $VENV"
[ -x "$VENV/bin/python" ] || "$PY" -m venv "$VENV"
VPY="$VENV/bin/python"
"$VPY" -m pip install -q --upgrade pip

echo "[2/5] Kilit (Windows paketleri hariç, sabit sürümler)"
"$VPY" - "$LOCK" "$TMP/lock_linux.txt" "$WINDOWS_ONLY" <<'EOF'
import re, sys
src, dst, skip = sys.argv[1], sys.argv[2], set(sys.argv[3].split())
keep = []
for line in open(src, encoding='utf-8'):
    line = line.strip()
    m = re.match(r'([A-Za-z0-9_.-]+)==', line)
    if m and re.sub(r'[-_.]+', '-', m[1]).lower() not in skip:
        keep.append(line)
open(dst, 'w', encoding='utf-8').write('\n'.join(keep) + '\n')
EOF
# Kilit tam (dolaylı bağımlılıklar dahil) olduğu için --no-deps ile birebir kurulur.
"$VPY" -m pip install -q --no-deps -r "$TMP/lock_linux.txt"

echo "[3/5] Ekler (requirements-bundle.txt) ve dolaylı bağımlılıkları"
# Kilitteki sürümler sabit kalır (-c); eklerin kilitte olmayan dolaylı bağımlılıkları çözülerek kurulur.
"$VPY" -m pip install -q -c "$TMP/lock_linux.txt" -r "$ROOT/requirements-bundle.txt" $LINUX_EXTRA

echo "[4/5] Doğrulama"
"$VPY" - "$TMP/lock_linux.txt" "$KNOWN_MISSING" <<'EOF'
import importlib, re, subprocess, sys
from importlib import metadata
lock, allowed = sys.argv[1], set(sys.argv[2].split())
bad = []
for line in open(lock, encoding='utf-8'):
    name, ver = line.strip().split('==')
    try:
        got = metadata.version(name)
    except metadata.PackageNotFoundError:
        bad.append(f'{name}: kurulu değil')
        continue
    if got != ver:
        bad.append(f'{name}: {got} (kilit {ver})')
# pip check: her paketin dolaylı bağımlılığı kurulu ve uyumlu mu?
out = subprocess.run([sys.executable, '-m', 'pip', 'check'], capture_output=True, text=True).stdout
for row in out.splitlines():
    m = re.search(r'requires ([A-Za-z0-9_.-]+)', row) or re.search(r'has requirement ([A-Za-z0-9_.-]+)', row)
    if m and re.sub(r'[-_.]+', '-', m[1]).lower() in allowed:
        continue
    if row.strip() and not row.startswith('No broken'):
        bad.append('pip check: ' + row)
for mod in ('psutil', 'google.genai', 'speech_recognition', 'requests', 'pptx', 'docx', 'openpyxl', 'markitdown', 'faster_whisper', 'playwright'):
    try:
        importlib.import_module(mod)
    except Exception as exc:
        bad.append(f'import {mod}: {type(exc).__name__}: {exc}')
if bad:
    print('Eksik/uyumsuz:\n  ' + '\n  '.join(bad)); sys.exit(1)
print('Tüm kilit paketleri doğru sürümde, dolaylı bağımlılıklar tam, python-pptx içe aktarıldı.')
EOF

if [ "$RUN_TESTS" = 1 ]; then
    echo "[5/5] Tam doğrulama (modules.validation)"
    cd "$ROOT" && "$VPY" -X utf8 -m modules.validation
else
    echo "[5/5] Testler için: $VPY -X utf8 -m modules.validation"
fi
