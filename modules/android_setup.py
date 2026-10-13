"""Short-lived, one-use Android provisioning grants; QR contains no API key."""
import copy
import secrets
import threading
import time

class SetupGrants:
    def __init__(self):
        self._lock = threading.Lock()
        self._grants = {}

    def issue(self, owner, payload):
        with self._lock:
            now = time.monotonic()
            self._grants = {c:v for c,v in self._grants.items() if v[2] > now and v[0] != owner}
            if len(self._grants) >= 100:
                self._grants.pop(next(iter(self._grants)))
            code = secrets.token_urlsafe(32)
            # No credential is retained in the grant table.
            clean = {k:copy.deepcopy(v) for k,v in payload.items() if k != 'k'}
            self._grants[code] = (owner, clean, now + 90)
            return code

    def redeem(self, code, key_for):
        with self._lock:
            grant = self._grants.pop(code, None)
        if not grant or grant[2] <= time.monotonic():
            return None
        key = key_for(grant[0])
        if not key:
            return None
        return {**grant[1], 'k':key}

    def clear(self, owner=None):
        with self._lock:
            if owner is None:
                self._grants.clear()
            else:
                self._grants = {c:v for c,v in self._grants.items() if v[0] != owner}
