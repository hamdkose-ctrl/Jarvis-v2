"""Git source comparison including Git/Windows-only line-ending conversion."""
import hashlib
from pathlib import Path

TEXT_SUFFIXES = {'.py', '.js', '.html', '.css', '.md', '.txt', '.json', '.bat', '.toml',
                 '.yaml', '.yml', '.java', '.gradle', '.properties', '.xml', '.svg', '.ps1'}


def blob_sha(data):
    return hashlib.sha1(b'blob ' + str(len(data)).encode('ascii') + b'\0' + data).hexdigest()


def blob_matches(path, data, remote_sha):
    if blob_sha(data) == remote_sha:
        return True
    if Path(path).suffix.lower() not in TEXT_SUFFIXES or b'\0' in data:
        return False
    lf = data.replace(b'\r\n', b'\n')
    return blob_sha(lf) == remote_sha or blob_sha(lf.replace(b'\n', b'\r\n')) == remote_sha
