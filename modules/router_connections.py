"""Owner connection metadata in existing user_models; never an inference/task scheduler."""

from copy import deepcopy
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit, urlunsplit
import uuid

from config import DATA_DIR
from modules import privacy, user_models
from modules.diagnostics import record_failure as _record_failure

PROTOCOLS = frozenset({"openai_compatible", "responses", "anthropic_messages"})
ROLES = frozenset(
    {"brain_understanding", "conversation", "public_research", "long_worker", "vision"}
)
BILLING = frozenset({"free", "trial", "paid", "unknown"})
_IDENT = re.compile(r"^[a-f0-9]{16,32}$")
_MODEL = re.compile(r"^[\w./:@-]{1,150}$")


def endpoint(value):
    if (
        not isinstance(value, str)
        or len(value) > 500
        or any(ord(c) < 33 for c in value)
        or "\\" in value
    ):
        raise ValueError("API adresi geçersiz.")
    try:
        uri = urlsplit(value)
        host = (uri.hostname or "").rstrip(".").lower()
        port = uri.port
        local = host == "localhost"
        try:
            local = local or ipaddress.ip_address(host).is_loopback
        except ValueError:
            pass
        if (
            not host
            or uri.username
            or uri.password
            or uri.query
            or uri.fragment
            or uri.scheme not in ("https", "http")
            or (uri.scheme == "http" and not local)
            or ".." in uri.path.split("/")
            or "%" in uri.netloc
        ):
            raise ValueError(
                "Uzak API HTTPS, yerel API loopback adresi kullanmalı; adres içinde anahtar olamaz."
            )
        if host == "nvidia.com" or host.endswith(".nvidia.com"):
            raise ValueError(
                "NVIDIA/NIM yalnız ayrı doğrulanmış deney kapsamında kullanılabilir."
            )
        netloc = ("[" + host + "]" if ":" in host else host) + (
            (":" + str(port)) if port else ""
        )
        return urlunsplit((uri.scheme, netloc, uri.path.rstrip("/"), "", ""))
    except (TypeError, ValueError) as exc:
        raise ValueError("API adresi veya endpoint kapsamı geçersiz.") from exc


def is_local(value):
    host = urlsplit(value).hostname
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except (ValueError, TypeError):
        return False


def _secret(owner, row, state):
    ref = row.get("secret_ref")
    if isinstance(ref, str) and ref.startswith("legacy:"):
        vendor = ref.removeprefix("legacy:")
        if vendor not in ("openai", "anthropic"):
            raise ValueError("Eski secret referansı geçersiz.")
        path = Path(DATA_DIR) / "keys" / (owner + "." + vendor + ".txt")
        if path.is_symlink():
            raise ValueError("Secret kaydı sembolik bağ olamaz.")
        protected = path.read_text(encoding="utf-8") if path.exists() else ""
    else:
        protected = state.get("secrets", {}).get(ref, "")
    if not isinstance(protected, str):
        raise ValueError("Secret kaydı geçersiz.")
    return privacy.unprotect(protected) if protected else ""


def migrate_legacy(owner):
    """Keep old keys in place; migrate metadata disabled with no network/paid test."""
    if not owner:
        return
    current = user_models.routing(owner)
    if current.get("legacy_migrated") is True:
        return

    def mutate(state, values):
        if state.get("legacy_migrated") is True:
            return
        rows = state.setdefault("connections", {})
        for vendor, protocol, url, label in (
            (
                "openai",
                "responses",
                "https://api.openai.com/v1",
                "Eski OpenAI bağlantısı",
            ),
            (
                "anthropic",
                "anthropic_messages",
                "https://api.anthropic.com/v1",
                "Eski Claude bağlantısı",
            ),
        ):
            folder = Path(DATA_DIR) / "keys"
            meta = folder / (owner + "." + vendor + ".json")
            key = folder / (owner + "." + vendor + ".txt")
            if not meta.exists() and not key.exists():
                continue
            if meta.is_symlink() or key.is_symlink():
                raise ValueError("Eski bağlantı sembolik bağ olamaz.")
            try:
                data = (
                    json.loads(meta.read_text(encoding="utf-8"))
                    if meta.exists()
                    else {}
                )
            except (OSError, ValueError):
                _record_failure("modules/router_connections.py:legacy_metadata")
                data = {}
            if not isinstance(data, dict):
                data = {}
            model = data.get("model") or data.get("candidate_model") or ""
            if not isinstance(model, str) or not _MODEL.fullmatch(model):
                model = ""
            ident = hashlib.sha256((owner + ":legacy:" + vendor).encode()).hexdigest()[
                :24
            ]
            rows.setdefault(
                ident,
                {
                    "id": ident,
                    "revision": 1,
                    "name": label,
                    "protocol": protocol,
                    "base_url": url,
                    "model": model,
                    "role": "conversation",
                    "billing": "paid",
                    "enabled": False,
                    "paid_enabled": False,
                    "data_scopes": [],
                    "secret_ref": "legacy:" + vendor,
                    "daily_requests": 25,
                    "max_output_tokens": 2000,
                    "workspace": str(data.get("workspace") or "")[:200],
                    "migration_pending": True,
                },
            )
        if values.get("provider") in ("openai", "anthropic"):
            state["legacy_selection"] = values["provider"]
            values["provider"] = "auto"
        state["legacy_migrated"] = True

    user_models.update_routing(owner, mutate)


def records(owner, *, state=None):
    if state is None:
        migrate_legacy(owner)
        state = user_models.routing(owner)
    rows = state.get("connections", {})
    if not isinstance(rows, dict) or len(rows) > 32:
        raise ValueError("Özel bağlantı kataloğu geçersiz.")
    for ident, row in rows.items():
        if (
            not isinstance(ident, str)
            or not _IDENT.fullmatch(ident)
            or not isinstance(row, dict)
            or row.get("id") != ident
            or row.get("protocol") not in PROTOCOLS
            or row.get("role") not in ROLES
            or row.get("billing") not in BILLING
            or type(row.get("revision")) is not int
            or row["revision"] < 1
            or type(row.get("enabled")) is not bool
            or type(row.get("paid_enabled")) is not bool
            or not isinstance(row.get("data_scopes"), list)
            or any(
                s not in ("conversation", "selected_content", "public")
                for s in row["data_scopes"]
            )
            or not isinstance(row.get("model"), str)
            or (
                not _MODEL.fullmatch(row["model"])
                and not (row.get("migration_pending") and not row["enabled"])
            )
            or type(row.get("daily_requests")) is not int
            or not 1 <= row["daily_requests"] <= 10000
            or type(row.get("max_output_tokens")) is not int
            or not 1 <= row["max_output_tokens"] <= 65536
            or endpoint(row.get("base_url")) != row["base_url"]
        ):
            raise ValueError("Özel bağlantı kaydı geçersiz; otomatik kullanılmadı.")
    return deepcopy(rows)


def snapshot(owner):
    rows = records(owner)
    state = user_models.routing(owner)
    out = []
    for ident, row in rows.items():
        safe = {
            k: deepcopy(v) for k, v in row.items() if k not in ("secret_ref", "_secret")
        }
        ref = row.get("secret_ref")
        safe["has_key"] = (
            bool(
                (
                    Path(DATA_DIR)
                    / "keys"
                    / (owner + "." + ref.removeprefix("legacy:") + ".txt")
                ).exists()
            )
            if isinstance(ref, str) and ref.startswith("legacy:")
            else bool(state.get("secrets", {}).get(ref))
        )
        out.append(safe)
    return out


def save(owner, record, *, secret=None):
    if not isinstance(record, dict):
        raise ValueError("Özel bağlantı alanları geçersiz.")
    allowed = {
        "id",
        "name",
        "protocol",
        "base_url",
        "model",
        "role",
        "billing",
        "enabled",
        "paid_enabled",
        "data_scopes",
        "daily_requests",
        "max_output_tokens",
        "workspace",
        "free_pool",
        "daily_cost_microusd",
        "quota_group",
    }
    if set(record) - allowed:
        raise ValueError("Özel bağlantıda bilinmeyen alan var.")
    ident = record.get("id") or uuid.uuid4().hex[:24]
    if not isinstance(ident, str) or not _IDENT.fullmatch(ident):
        raise ValueError("Bağlantı kimliği geçersiz.")
    name = record.get("name")
    model = record.get("model")
    if (
        not isinstance(name, str)
        or not 1 <= len(name.strip()) <= 80
        or any(ord(c) < 32 for c in name)
    ):
        raise ValueError("Bağlantı adı geçersiz.")
    if not isinstance(model, str) or not _MODEL.fullmatch(model):
        raise ValueError("Exact model kimliği gerekli.")
    if "nemotron" in model.casefold():
        raise ValueError("Nemotron yalnız ayrı deney profiline aittir.")
    if (
        record.get("protocol") not in PROTOCOLS
        or record.get("role") not in ROLES
        or record.get("billing") not in BILLING
    ):
        raise ValueError("Protokol, kullanım rolü veya ücret sınıfı geçersiz.")
    for flag in ("enabled", "paid_enabled", "free_pool"):
        if type(record.get(flag, False)) is not bool:
            raise ValueError("Etkinleştirme seçimi geçersiz.")
    scopes = record.get("data_scopes", [])
    if not isinstance(scopes, list) or any(
        v not in ("conversation", "selected_content", "public") for v in scopes
    ):
        raise ValueError("Veri kapsamı geçersiz.")
    daily = record.get("daily_requests", 25)
    output = record.get("max_output_tokens", 2000)
    if (
        type(daily) is not int
        or not 1 <= daily <= 10000
        or type(output) is not int
        or not 1 <= output <= 65536
    ):
        raise ValueError("Yerel çağrı/çıktı bütçesi geçersiz.")
    if (
        record.get("enabled")
        and record["billing"] != "free"
        and record.get("paid_enabled") is not True
    ):
        raise ValueError(
            "Trial/paid/unknown bağlantı için açık ücretli kullanım tercihi gerekli."
        )
    group = record.get("quota_group", "")
    if not isinstance(group, str) or (
        group and not re.fullmatch(r"[\w.:-]{1,100}", group)
    ):
        raise ValueError("Kota grubu geçersiz.")
    money = record.get("daily_cost_microusd")
    if money is not None and (type(money) is not int or not 1 <= money <= 10**12):
        raise ValueError("Parasal tavan geçersiz.")
    base = endpoint(record.get("base_url"))
    workspace = record.get("workspace", "")
    if (
        not isinstance(workspace, str)
        or len(workspace) > 200
        or any(ord(c) < 32 for c in workspace)
    ):
        raise ValueError("Çalışma alanı kimliği geçersiz.")
    protected = None
    if secret is not None:
        if (
            not isinstance(secret, str)
            or len(secret) > 4096
            or any(ord(c) < 32 for c in secret)
        ):
            raise ValueError("Secret biçimi geçersiz.")
        protected = privacy.protect(secret.strip()) if secret.strip() else ""
        if protected and sys.platform == "win32" and not protected.startswith("dpapi:"):
            raise ValueError("Windows secret koruması çalışmadı.")
    migrate_legacy(owner)

    def mutate(state, _values):
        rows = state.setdefault("connections", {})
        old = rows.get(ident, {})
        if len(rows) >= 32 and not old:
            raise ValueError("En çok32 özel bağlantı kaydedilebilir.")
        if record.get("id") and not old:
            raise ValueError("Bağlantı bu kullanıcıda yok.")
        row = {k: deepcopy(v) for k, v in record.items() if k in allowed}
        row.update(
            id=ident,
            name=name.strip(),
            base_url=base,
            revision=old.get("revision", 0) + 1,
            data_scopes=sorted(set(scopes)),
            daily_requests=daily,
            max_output_tokens=output,
            enabled=record.get("enabled", False),
            paid_enabled=record.get("paid_enabled", False),
            secret_ref=old.get("secret_ref", ident),
            migration_pending=False,
            free_pool=record.get("free_pool", False),
            daily_cost_microusd=money,
        )
        if protected is not None:
            row["secret_ref"] = ident
            state.setdefault("secrets", {})[ident] = protected
        if (
            row["enabled"]
            and not _secret(owner, row, state)
            and not is_local(row["base_url"])
        ):
            raise ValueError("Etkin bağlantının anahtarı yok.")
        if row["enabled"] and not row["free_pool"]:
            for other in rows.values():
                if (
                    other.get("role") == row["role"]
                    and other.get("id") != ident
                    and other.get("enabled")
                    and not other.get("free_pool")
                ):
                    other["enabled"] = False
                    other["revision"] = other.get("revision", 0) + 1
        rows[ident] = row

    user_models.update_routing(owner, mutate)
    return next(row for row in snapshot(owner) if row["id"] == ident)


def remove(owner, ident):
    def mutate(state, _values):
        rows = state.setdefault("connections", {})
        if ident not in rows:
            raise ValueError("Bağlantı bu kullanıcıda yok.")
        rows.pop(ident)
        state.setdefault("secrets", {}).pop(ident, None)

    user_models.update_routing(owner, mutate)


def resolve(owner, ident, *, revision=None, require_enabled=True):
    migrate_legacy(owner)
    state = user_models.routing(owner)
    row = records(owner, state=state).get(ident)
    if not isinstance(row, dict) or (
        revision is not None and row.get("revision") != revision
    ):
        raise ValueError("Bağlantı kaydı değişmiş veya başka kullanıcıya ait.")
    if require_enabled and row.get("enabled") is not True:
        raise ValueError("Özel bağlantı etkin değil.")
    if (
        row.get("billing") != "free"
        and row.get("paid_enabled") is not True
        and require_enabled
    ):
        raise ValueError("Ücretli kullanım etkin değil.")
    endpoint(row["base_url"])
    secret = _secret(owner, row, state)
    return row, secret


def free_pool_eligible(owner, row):
    """Reviewed account+endpoint+model facts; UI free/trial labels are not proof."""
    from modules import model_capabilities
    import time

    try:
        _current, secret = resolve(owner, row["id"], revision=row["revision"])
    except (ValueError, OSError):
        return False
    identity = (
        owner,
        row["base_url"],
        hashlib.sha256(secret.encode()).hexdigest(),
        row["model"],
    )
    facts = model_capabilities.CUSTOM_FREE_ACCOUNTS.get(identity)
    return bool(
        row.get("free_pool") is True
        and row["billing"] == "free"
        and isinstance(facts, dict)
        and model_capabilities._valid_entry(facts, now=time.time())
        and facts.get("no_paid_billing") is True
        and facts.get("account_eligible") is True
        and set(row["data_scopes"]) <= set(facts.get("data_scopes", ()))
    )


def capability_binding(owner, row):
    from modules import provider_protocols

    _current, secret = resolve(
        owner, row["id"], revision=row["revision"], require_enabled=False
    )
    facts = [
        owner,
        row["id"],
        row["revision"],
        row["base_url"],
        row["protocol"],
        row["model"],
        secret,
        hashlib.sha256(Path(provider_protocols.__file__).read_bytes()).hexdigest(),
    ]
    return hashlib.sha256(json.dumps(facts, sort_keys=True).encode()).hexdigest()


def vision_ready(owner, row):
    import time

    evidence = (
        user_models.routing(owner).get("vision_observations", {}).get(row["id"], {})
    )
    if not isinstance(evidence, dict) or evidence.get("expires_at", 0) <= time.time():
        return False
    try:
        return (
            evidence.get("binding") == capability_binding(owner, row)
            and evidence.get("verified_vision") is True
        )
    except (ValueError, OSError):
        return False


def record_vision_observation(owner, row):
    """Only the explicit image challenge invokes this after an exact match; no UI assertion."""
    import time

    binding = capability_binding(owner, row)

    def mutate(state, _values):
        current = state.get("connections", {}).get(row["id"])
        if not current or current.get("revision") != row["revision"]:
            raise ValueError("Görüntü denemesinde bağlantı değişti.")
        state.setdefault("vision_observations", {})[row["id"]] = {
            "verified_vision": True,
            "binding": binding,
            "expires_at": time.time() + 7 * 86400,
            "source": "explicit_synthetic_image_challenge",
        }

    user_models.update_routing(owner, mutate)
