"""Offline PC smoke checks; no Jarvis imports, model calls or application writes."""
from __future__ import annotations

import sys

# Third-party device enumeration must not leave import caches in the installation.
sys.dont_write_bytecode = True

import argparse
import ast
import ctypes
import http.client
import importlib
import importlib.metadata as metadata
import json
import ntpath
import os
import re
import tempfile
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

PASS, WARN, FAIL, SKIP = 'GEÇTİ', 'UYARI', 'BAŞARISIZ', 'ATLANDI'
TR = timezone(timedelta(hours=3))
SAMPLE = 'ışğüöçİ'
MAX_READ = 4 * 1024 * 1024
WINDOWS_PACKAGES = {'comtypes', 'pycaw', 'pywin32', 'pypiwin32', 'wmi'}
FOLDERS = {'Masaüstü': 'B4BFCC3A-DB2C-424C-B029-7FE99A87C641',
           'Belgeler': 'FDD39AD0-238F-46AF-ADB4-6C85480369C7',
           'İndirilenler': '374DE290-123F-4565-9164-39C4925E467B'}
SCOPES = {'gmail.readonly': 'Gmail okuma', 'gmail.send': 'Gmail gönderme',
          'gmail.modify': 'Gmail değiştirme', 'mail.google.com': 'Gmail tam erişim',
          'calendar.readonly': 'Takvim okuma', 'calendar': 'Takvim yazma',
          'calendar.events': 'Takvim etkinlik yazma',
          'calendar.events.readonly': 'Takvim etkinlik okuma', 'tasks': 'Görevler yazma',
          'youtube.readonly': 'YouTube okuma', 'youtube.upload': 'YouTube yükleme',
          'youtube.force-ssl': 'YouTube değiştirme'}
ERROR_TYPES = ('TimeoutError', 'ConnectionError', 'PermissionError', 'FileNotFoundError',
               'ValueError', 'RuntimeError', 'TypeError', 'KeyError', 'OSError',
               'UnicodeError', 'UnicodeDecodeError', 'JSONDecodeError', 'ModuleNotFoundError',
               'HTTPError', 'APIError', 'ClientError', 'ServerError', 'RateLimitError')


class MissingModule(Exception):
    pass


@dataclass
class Context:
    repo: Path
    data: Path
    reports: Path
    profile: str | None
    windows: bool = field(default_factory=lambda: sys.platform == 'win32')
    now: datetime = field(default_factory=lambda: datetime.now(TR))
    encoding: str = field(default_factory=lambda: sys.stdout.encoding or 'utf-8')


def require(ctx, relative):
    if not (ctx.repo / relative).is_file():
        raise MissingModule('modül yok: ' + relative)


def small_read(path, limit=MAX_READ):
    if path.is_symlink():
        raise ValueError('link')
    with path.open('rb') as handle:
        raw = handle.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('limit')
    return raw


def read_json(path):
    return json.loads(small_read(path).decode('utf-8-sig'))


def assignments(path):
    tree = ast.parse(small_read(path).decode('utf-8-sig'))
    return {node.targets[0].id: node.value for node in tree.body
            if isinstance(node, ast.Assign) and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)}


def active_profile(repo, data):
    """Mirror personalization.slugify without importing config (which creates dirs)."""
    try:
        name = small_read(data / 'active_user.txt', 1024).decode('utf-8').strip()
    except FileNotFoundError:
        node = assignments(repo / 'config.py').get('DEFAULT_USER')
        name = ast.literal_eval(node) if node is not None else ''
    if not isinstance(name, str):
        raise ValueError('profile')
    name = name.translate(str.maketrans('çğıöşüÇĞİÖŞÜ', 'cgiosuCGIOSU')).lower()
    return re.sub('[^a-z0-9]', '', name)[:64] or 'default'


def requirements(path, root, seen=None):
    """Follow local -r files only; never run pip or install anything."""
    seen = set() if seen is None else seen
    path = path.resolve()
    path.relative_to(root.resolve())
    if path in seen:
        return []
    if len(seen) >= 10:
        raise ValueError('requirements limit')
    seen.add(path)
    result = []
    for line in small_read(path).decode('utf-8-sig').splitlines():
        line = line.split('#', 1)[0].strip()
        if not line:
            continue
        match = re.fullmatch(r'(?:-r\s*|--requirement\s+)([^\s]+)', line)
        if match:
            result.extend(requirements(path.parent / match[1], root, seen))
        else:
            result.append(line)
    return result


def check_python(ctx):
    if sys.version_info[:2] < (3, 10):
        return FAIL, 'Python 3.10 altı; betiğin desteklediği sözdizimi uygun değil.'
    missing, different, unknown = [], 0, 0
    lines = requirements(ctx.repo / 'requirements.txt', ctx.repo)
    for line in lines:
        # Current requirements.txt includes the fully pinned requirements.lock.txt.
        match = re.fullmatch(r'([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+!-]+)', line)
        if not match:
            unknown += 1
            continue
        name, wanted = match.groups()
        if not ctx.windows and name.lower() in WINDOWS_PACKAGES:
            continue
        try:
            installed = metadata.version(name)
        except metadata.PackageNotFoundError:
            missing.append(name)
            continue
        different += installed != wanted
    if not lines:
        return FAIL, 'Gereksinim listesi boş.'
    prefix = 'Python %d.%d; ' % sys.version_info[:2]
    if missing:
        return FAIL, prefix + f'eksik paket: {len(missing)} (' + ', '.join(missing[:5]) + ').'
    if different or unknown or sys.version_info[:2] != (3, 13):
        return WARN, prefix + f'kilitten farklı: {different}; yorumlanamayan satır: {unknown}; CI referansı 3.13.'
    return PASS, prefix + f'{len(lines)} gereksinim mevcut ve sabit sürümlerle eşleşiyor.'


def check_encoding(ctx):
    # This is the only disposable file; its location is ALWAYS the report directory.
    path = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=ctx.reports,
                                         prefix='kodlama_', suffix='.tmp', delete=False) as handle:
            path = Path(handle.name)
            handle.write(SAMPLE)
        if path.read_text(encoding='utf-8') != SAMPLE:
            return FAIL, 'Rapor klasöründe UTF-8 yazma/okuma eşleşmedi.'
    finally:
        if path is not None:
            path.unlink()  # Only our own temporary encoding probe, never a Jarvis file.
    try:
        if SAMPLE.encode(ctx.encoding).decode(ctx.encoding) != SAMPLE:
            return WARN, 'UTF-8 dosya doğru; konsol Türkçe dönüşümü eşleşmedi.'
    except (UnicodeError, LookupError):
        return WARN, 'UTF-8 dosya doğru; konsol Türkçe karakterleri desteklemiyor.'
    return PASS, 'Türkçe metin rapor klasöründe ve konsol kodlamasında kayıpsız.'


def known_folder(identifier):
    class GUID(ctypes.Structure):
        _fields_ = [('a', ctypes.c_uint32), ('b', ctypes.c_uint16),
                    ('c', ctypes.c_uint16), ('d', ctypes.c_ubyte * 8)]
    shell = ctypes.WinDLL('shell32', use_last_error=True)
    ole = ctypes.WinDLL('ole32', use_last_error=True)
    query = shell.SHGetKnownFolderPath
    query.argtypes = [ctypes.POINTER(GUID), ctypes.c_uint32, ctypes.c_void_p,
                      ctypes.POINTER(ctypes.c_wchar_p)]
    query.restype = ctypes.c_long
    ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    ole.CoTaskMemFree.restype = None
    guid = GUID.from_buffer_copy(uuid.UUID(identifier).bytes_le)
    pointer = ctypes.c_wchar_p()
    try:
        # DONT_VERIFY, never CREATE: retrieving the path cannot create a folder.
        if query(ctypes.byref(guid), 0x4000, None, ctypes.byref(pointer)) != 0:
            raise OSError('known folder')
        if not pointer.value:
            raise OSError('empty known folder')
        return Path(pointer.value)
    finally:
        if pointer:
            ole.CoTaskMemFree(ctypes.cast(pointer, ctypes.c_void_p))


def jarvis_folder(ctx, label):
    """Use modules/files.py's actual _FOLDERS and audited folder_path semantics.

    Static reading avoids importing config, llm, diagnostics or application state.
    Reject a changed helper instead of running arbitrary repository code.
    """
    path = ctx.repo / 'modules/files.py'
    require(ctx, 'modules/files.py')
    tree = ast.parse(small_read(path).decode('utf-8-sig'))
    template = ast.parse('''def folder_path(candidates: tuple[str, ...]) -> Path | None:
    home = Path.home()
    for c in candidates:
        p = home / c
        if p.is_dir():
            return p
    return None
''').body[0]
    actual = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'folder_path'), None)
    if actual is None or ast.dump(actual) != ast.dump(template):
        raise MissingModule('Klasör çözümünün biçimi değişmiş; yan etki riski nedeniyle çalıştırılmadı.')
    folders = ast.literal_eval(assignments(path)['_FOLDERS'])
    for _, candidates, _, title in folders:
        if title == label:
            return next((Path.home() / c for c in candidates if (Path.home() / c).is_dir()), None)
    raise MissingModule('Jarvis klasör çözümünde istenen klasör yok.')


def same_path(a, b):
    return ntpath.normcase(ntpath.normpath(str(a))) == ntpath.normcase(ntpath.normpath(str(b)))


def check_folders(ctx):
    if not ctx.windows:
        return SKIP, 'Windows değil; Known Folder API denenmedi.'
    details, mismatch = [], False
    for label, identifier in FOLDERS.items():
        actual, jarvis = known_folder(identifier), jarvis_folder(ctx, label)
        matches = jarvis is not None and same_path(actual, jarvis)
        redirected = any('onedrive' in part.casefold() for part in actual.parts)
        for variable in ('OneDrive', 'OneDriveConsumer', 'OneDriveCommercial'):
            root = os.getenv(variable)
            if root and (same_path(root, actual) or ntpath.normcase(str(actual)).startswith(ntpath.normcase(root.rstrip('\\/') + os.sep))):
                redirected = True
        mismatch |= not matches
        details.append(label + ': ' + ('eşleşiyor' if matches else 'Jarvis yolu farklı/yok')
                       + ', OneDrive ' + ('var' if redirected else 'yok'))
    return (WARN if mismatch else PASS), '; '.join(details) + '.'


def check_writable(ctx):
    require(ctx, 'config.py')
    paths = [ctx.data, ctx.data / 'users']
    if ctx.profile:
        paths.append(ctx.data / 'users' / (ctx.profile + '.json'))
    absent = 0
    for path in paths:
        if not path.exists():
            absent += 1
            continue
        if not os.access(path, os.W_OK):
            return FAIL, 'Veri/profil konumlarında yazma izni görünmüyor; yazma denenmedi.'
    if absent:
        return WARN, f'Veri/profil konumlarından {absent} tanesi yok; hiçbir klasör oluşturulmadı.'
    if not ctx.profile:
        return WARN, 'Veri klasörü izinleri uygun; aktif profil okunamadı, profil izni bilinmiyor.'
    return PASS, 'Veri/profil izin ön kontrolü uygun; gerçek yazma veya kesin ACL doğrulaması yapılmadı.'


def check_google(ctx):
    require(ctx, 'modules/google_api.py')
    if not ctx.profile:
        return WARN, 'Aktif profil okunamadı; kullanıcı token alanına bakılmadı.'
    folder = ctx.data / 'google_users' / ctx.profile
    names = ('google_token.json', 'google_tasks_token.json', 'google_gmail_write_token.json',
             'google_youtube_read_token.json', 'google_youtube_write_token.json', 'google_youtube_reply_write_token.json')
    paths = [folder / name for name in names if (folder / name).is_file()]
    legacy = False
    if not paths:
        paths = [ctx.data / name for name in names if (ctx.data / name).is_file()]
        legacy = bool(paths)
    if not paths:
        return WARN, 'Google token dosyası yok; bağlantı denenmedi.'
    expired, unknown, labels, other = 0, 0, set(), False
    for path in paths:
        saved = read_json(path)
        if not isinstance(saved, dict) or not isinstance(saved.get('token'), str) or not saved['token']:
            return FAIL, 'Token dosyası var fakat yapısı geçerli görünmüyor.'
        scopes = saved.get('scopes', [])
        if isinstance(scopes, str):
            scopes = scopes.split()
        if not isinstance(scopes, list) or not all(isinstance(s, str) for s in scopes):
            return FAIL, 'Token kapsam alanı geçerli görünmüyor.'
        if not scopes:
            unknown += 1
        for scope in scopes:
            key = scope.removeprefix('https://www.googleapis.com/auth/')
            if scope == 'https://mail.google.com/':
                key = 'mail.google.com'
            if key in SCOPES:
                labels.add(SCOPES[key])
            else:
                other = True  # Never echo an unrecognised value from a credential file.
        expiry = saved.get('expiry')
        if not expiry:
            unknown += 1
        else:
            stamp = datetime.fromisoformat(expiry.replace('Z', '+00:00'))
            stamp = stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)
            expired += stamp <= ctx.now
    note = (f'{len(paths)} token var; kapsamlar: ' + (', '.join(sorted(labels)) or 'bilinmiyor')
            + ('; diğer kapsam var' if other else '') + f'; süresi dolmuş: {expired}; belirsiz alan: {unknown}.')
    if legacy:
        note += ' Eski ortak token; kullanıcı eşleşmesi doğrulanmadı.'
    note += ' İptal/yenileme ağdan denenmedi.'
    return (WARN if expired or unknown or legacy or other else PASS), note


def registry_value(hive, path, name, view=0):
    import winreg
    try:
        with winreg.OpenKey(hive, path, 0, winreg.KEY_READ | view) as key:
            return winreg.QueryValueEx(key, name)[0]
    except FileNotFoundError:
        return None


def check_outlook(ctx):
    if not ctx.windows:
        return SKIP, 'Windows değil; COM kaydı okunmadı.'
    import winreg
    for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
        value = registry_value(winreg.HKEY_CLASSES_ROOT, r'Outlook.Application\CLSID', '', view)
        if value:
            try:
                uuid.UUID(str(value).strip('{}'))
            except ValueError:
                return FAIL, 'Outlook COM kaydı var fakat CLSID geçerli görünmüyor.'
            return PASS, 'Klasik Outlook COM kaydı var; Outlook açılmadı, çalışması denenmedi.'
    return WARN, 'Outlook COM kaydı yok; yeni Outlook COM sunmayabilir.'


def microphone_privacy():
    import winreg
    path = r'Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone'
    values = [registry_value(hive, key, 'Value')
              for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER)
              for key in (path, path + r'\NonPackaged')]
    # Documented policy: 2 means force-deny. Never change policy/consent keys.
    policy = registry_value(winreg.HKEY_LOCAL_MACHINE,
                            r'Software\Policies\Microsoft\Windows\AppPrivacy', 'LetAppsAccessMicrophone')
    if policy == 2 or any(str(v).lower() == 'deny' for v in values):
        return False
    if values[0] == 'Allow' and values[3] == 'Allow':
        return True
    return None


def check_audio(ctx):
    if not ctx.windows:
        return SKIP, 'Windows değil; cihaz/gizlilik kontrolü yapılmadı.'
    try:
        sounddevice = importlib.import_module('sounddevice')
    except ImportError:
        return SKIP, 'modül yok: sounddevice; cihaz/gizlilik kontrolü tamamlanamadı.'
    try:
        devices = sounddevice.query_devices()  # No stream, playback or recording.
    except (OSError, RuntimeError):
        return FAIL, 'Ses cihazları listelenemedi; kayıt/çalma yapılmadı.'
    inputs = sum(d.get('max_input_channels', 0) > 0 for d in devices)
    outputs = sum(d.get('max_output_channels', 0) > 0 for d in devices)
    try:
        privacy = microphone_privacy()
    except OSError:
        return FAIL, f'Giriş cihazı: {inputs}; çıkış cihazı: {outputs}; gizlilik kaydı okunamadı.'
    detail = f'Giriş cihazı: {inputs}; çıkış cihazı: {outputs}; mikrofon izni '
    detail += 'açık görünüyor.' if privacy is True else 'kapalı.' if privacy is False else 'belirsiz.'
    if not inputs or not outputs or privacy is False:
        return FAIL, detail + ' Kayıt/çalma yapılmadı.'
    return (PASS if privacy is True else WARN), detail + ' Gerçek ses ve uygulama erişimi denenmedi.'


def ollama_version():
    connection = http.client.HTTPConnection('127.0.0.1', 11434, timeout=2)
    try:
        connection.request('GET', '/api/version')
        response = connection.getresponse()
        raw = response.read(4097)
        if response.status != 200 or len(raw) > 4096:
            return False
        payload = json.loads(raw)
        return isinstance(payload, dict) and isinstance(payload.get('version'), str) and bool(payload['version'].strip())
    finally:
        connection.close()


def check_ollama(ctx):
    try:
        valid = ollama_version()
    except (OSError, http.client.HTTPException, ValueError):
        return FAIL, 'Yerel 11434 portuna erişilemedi veya sürüm yanıtı okunamadı; model çağrılmadı.'
    if not valid:
        return FAIL, 'Yerel 11434 sürüm uç noktası geçerli yanıt vermedi; model çağrılmadı.'
    return PASS, '127.0.0.1:11434 sürüm uç noktası yanıtladı; model çağrılmadı.'


def check_quota(ctx):
    require(ctx, 'modules/usage_meter.py')
    if not ctx.profile:
        return WARN, 'Aktif profil okunamadı; kullanıcı kota alanına bakılmadı.'
    base = ctx.data / 'kota' / (ctx.profile + '.jsonl')
    paths = [p for p in (base.with_suffix('.jsonl.1'), *sorted(base.parent.glob(base.name + '.archive-*')), base) if p.exists()]
    if not paths:
        return WARN, 'Kota kayıt dosyası yok; bugünkü çağrı sayısı bilinmiyor.'
    count, bad, total_bytes = 0, 0, 0
    partial = len(paths) > 64 or base.with_suffix('.jsonl.1') in paths
    for path in paths[:64]:
        raw = small_read(path)
        total_bytes += len(raw)
        if total_bytes > 16 * 1024 * 1024:
            partial = True
            break
        for line in raw.splitlines():
            try:
                row = json.loads(line)
                if not isinstance(row, dict) or not all(isinstance(row.get(k), str) for k in ('t', 'p', 's', 'r')) or not all(type(row.get(k)) is int and row[k] >= 0 for k in ('i', 'o')):
                    raise ValueError('row')
                stamp = datetime.fromisoformat(row['t'])
                if stamp.tzinfo is None:
                    raise ValueError('timezone')
                count += stamp.astimezone(TR).date() == ctx.now.astimezone(TR).date()
            except (ValueError, TypeError):
                bad += 1
    note = f'Bugün okunabilen çağrı: {count}; bozuk satır: {bad}.'
    if partial or bad:
        return WARN, note + ' Sayaç kısmi; toplam kesin değil.'
    return PASS, note + ' İçerik/model adı rapora alınmadı.'


def check_log(ctx):
    require(ctx, 'modules/engine_runtime.py')
    path = ctx.data / 'jarvis.log'
    if not path.exists():
        return WARN, 'jarvis.log yok; hata sayısı bilinmiyor.'
    if path.is_symlink():
        raise ValueError('link')
    with path.open('rb') as handle:
        handle.seek(0, 2)
        start = max(0, handle.tell() - 1024 * 1024)
        handle.seek(start)
        raw = handle.read(1024 * 1024)
    lines = raw.splitlines()
    if start:
        lines = lines[1:]  # discard a possibly incomplete leading line
    limited = bool(start and len(lines) < 200)
    lines = [line.decode('utf-8', errors='replace') for line in lines[-200:]]
    encoding_issue = any('\ufffd' in line for line in lines)
    levels = Counter()
    types = Counter()
    pattern = r'^\d{4}-\d\d-\d\d\s+\S+\s+(WARNING|ERROR|CRITICAL)\b'
    for line in lines:
        found = re.match(pattern, line)
        if found:
            levels[found[1]] += 1
        for kind in ERROR_TYPES:
            if re.search(r'\b' + kind + r'\b', line):
                types[kind] += 1
    errors, warnings = levels['ERROR'] + levels['CRITICAL'], levels['WARNING']
    note = f'Son {len(lines)} satır: hata {errors}, uyarı {warnings}; türler: '
    note += ', '.join(k + ' ' + str(v) for k, v in sorted(types.items())) or 'tanınan hata türü yok'
    if limited:
        note += '; 1 MiB sınırı nedeniyle son 200 satır tamamlanamadı'
    if encoding_issue:
        note += '; UTF-8 kodlaması bozuk görünüyor'
    return (WARN if errors or warnings or limited or encoding_issue else PASS), note + '. İçerik rapora alınmadı.'


CHECKS = (('Python/paketler', check_python), ('Türkçe kodlama', check_encoding),
          ('Windows klasörleri', check_folders), ('Veri/profil izinleri', check_writable),
          ('Google token', check_google), ('Outlook', check_outlook),
          ('Ses/gizlilik', check_audio), ('Ollama', check_ollama),
          ('Kota sayacı', check_quota), ('Günlük', check_log))


def run_checks(ctx):
    rows = []
    for label, check in CHECKS:
        try:
            status, reason = check(ctx)
        except MissingModule as exc:
            status, reason = SKIP, exc.args[0]
        except Exception:
            # Exception messages/tracebacks can contain paths, credentials or log contents.
            status, reason = FAIL, 'Kontrol okunamadı veya geçerli yanıt vermedi; sonraki kontrole geçildi.'
        rows.append((label, status, reason))
    return rows


def summary(rows, now):
    counts = Counter(status for _, status, _ in rows)
    lines = ['JARVIS PC DUMAN TESTİ — ' + now.astimezone(TR).strftime('%Y-%m-%d %H:%M'),
             'Salt okunur ön kontrol; model çağrısı, kayıt/çalma ve hesap yenileme yapılmaz.']
    lines.extend(f'{index}. {label}: {status} — {reason}' for index, (label, status, reason) in enumerate(rows, 1))
    lines.append('Toplam: ' + ', '.join(f'{state} {counts[state]}' for state in (PASS, WARN, FAIL, SKIP)))
    return '\n'.join(lines) + '\n'


def console_write(text, stream):
    try:
        stream.write(text)
    except UnicodeEncodeError:
        encoding = stream.encoding or 'ascii'
        stream.write(text.encode(encoding, errors='backslashreplace').decode(encoding))


def main(argv=None):
    parser = argparse.ArgumentParser(description='Jarvis PC salt okunur duman testi; model/kota tüketmez.')
    parser.add_argument('--rapor-klasoru', type=Path, help='Varsayılan: depo/duman_raporlari')
    parser.add_argument('--veri-klasoru', type=Path, help='Varsayılan: JARVIS_DATA_DIR veya ~/.jarvis')
    parser.add_argument('--profil', help='İsteğe bağlı profil dosyasının uzantısız adı')
    args = parser.parse_args(argv)
    repo = Path(__file__).resolve().parents[1]
    data = args.veri_klasoru or Path(os.getenv('JARVIS_DATA_DIR') or Path.home() / '.jarvis')
    reports = args.rapor_klasoru or repo / 'duman_raporlari'
    if args.profil and not re.fullmatch(r'[\w-]{1,64}', args.profil):
        parser.error('Profil adı yalnız harf, rakam, _ ve - içerebilir (en çok 64).')
    try:
        profile = args.profil or active_profile(repo, data)
    except Exception:
        profile = None  # A broken profile must not prevent the other PC checks.
    try:
        reports.mkdir(parents=True, exist_ok=True)
    except OSError:
        console_write('Rapor klasörü oluşturulamadı; uygulama dosyaları değiştirilmedi.\n', sys.stdout)
        return 2
    ctx = Context(repo, data, reports, profile)
    rows = run_checks(ctx)
    text = summary(rows, ctx.now)
    filename = 'duman_raporu_' + ctx.now.strftime('%Y%m%d_%H%M%S_%f') + '.txt'
    try:
        # Exclusive creation: never truncate an existing report or follow a filename symlink.
        with (reports / filename).open('x', encoding='utf-8', newline='\n') as handle:
            handle.write(text)
    except OSError:
        console_write(text + 'Rapor dosyası yazılamadı.\n', sys.stdout)
        return 2
    console_write(text + 'Rapor: ' + filename + ' (seçilen rapor klasöründe).\n', sys.stdout)
    return 1 if any(state == FAIL for _, state, _ in rows) else 0


if __name__ == '__main__':
    raise SystemExit(main())
