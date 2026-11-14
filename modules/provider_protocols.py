"""One transport attempt for an owner-bound custom connection; no vendor selection/retry."""

import base64
import mimetypes
from pathlib import Path
import requests

from modules import privacy, requests_state, usage_meter
from modules.diagnostics import record_failure as _record_failure


class ProtocolError(RuntimeError):
    def __init__(
        self, message, *, status_code=None, reason_code="PROVIDER_CUSTOM_ERROR"
    ):
        super().__init__(message)
        self.status_code = status_code
        self.reason_code = reason_code


def _request(connection, secret, method, path, body=None):
    from modules import llm

    requests_state.check()
    from modules.router_connections import is_local

    if not secret and not is_local(connection["base_url"]):
        raise ProtocolError(
            "Özel bağlantının anahtarı yok.",
            reason_code="PROVIDER_CONFIGURATION_REQUIRED",
        )
    headers = {"Content-Type": "application/json"}
    if connection["protocol"] == "anthropic_messages":
        headers.update({"x-api-key": secret, "anthropic-version": "2023-06-01"})
        if connection.get("workspace"):
            headers["anthropic-workspace-id"] = connection["workspace"]
    elif secret:
        headers["Authorization"] = "Bearer " + secret
    try:
        response = requests.request(
            method,
            connection["base_url"] + path,
            headers=headers,
            json=body,
            timeout=llm.transport_timeouts(5, 45),
            allow_redirects=False,
        )
    except requests.RequestException as exc:
        _record_failure("modules/provider_protocols.py:transport")
        raise ProtocolError(
            "Özel API bağlantısı yanıt vermedi; üretim yapılmış olabilir.",
            reason_code="PROVIDER_TIMEOUT",
        ) from exc
    # Definitive identity/quota findings must retain their type/status even if
    # the enclosing request budget expired while the provider was responding.
    if response.status_code != 200:
        usage_meter.observe_limits(
            "custom:" + connection["id"], connection["model"], response.headers
        )
        error = ProtocolError(
            "Özel API isteği başarısız (HTTP " + str(response.status_code) + ").",
            status_code=response.status_code,
        )
        retry = response.headers.get("Retry-After")
        if isinstance(retry, str) and retry.isdigit():
            error.retry_after = min(86400, int(retry))
        raise error
    try:
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Invalid response envelope")
        return data, response.headers
    except ValueError as exc:
        _record_failure("modules/provider_protocols.py:response_envelope")
        raise ProtocolError("Özel API yanıtı okunamadı.") from exc


def generate(
    owner, connection, secret, messages, system, max_tokens, *, image_path=None
):
    from modules.router_connections import is_local

    if privacy.mode() == "gizli" or (
        privacy.mode() == "yerel" and not is_local(connection["base_url"])
    ):
        raise ProtocolError("Bu gizlilik modunda özel bulut bağlantısı kullanılmaz.")
    if not 0 < max_tokens <= connection["max_output_tokens"]:
        raise ProtocolError("Özel bağlantı çıktı bütçesi aşıldı.")
    rows = [
        {"role": m["role"], "content": privacy.redact(str(m["content"]))}
        for m in messages
    ]
    if not rows or any(
        row["role"] not in ("user", "assistant", "system") for row in rows
    ):
        raise ProtocolError("Mesaj rolleri geçersiz.")
    system = privacy.redact(system)
    image = None
    if image_path:
        path = Path(image_path)
        mime = mimetypes.guess_type(str(path))[0]
        if (
            mime not in ("image/png", "image/jpeg", "image/webp")
            or not 0 < path.stat().st_size <= 20 * 1024 * 1024
        ):
            raise ProtocolError("Görüntü biçimi/boyutu desteklenmiyor.")
        image = {
            "mime": mime,
            "data": base64.b64encode(path.read_bytes()).decode("ascii"),
        }
    model = connection["model"]
    protocol = connection["protocol"]
    provider = "custom:" + connection["id"]
    sent = usage_meter.size(rows, system)
    metered = False
    try:
        if protocol == "responses":
            items = []
            for index, row in enumerate(rows):
                content = row["content"]
                if image and index == len(rows) - 1:
                    content = [
                        {"type": "input_text", "text": content},
                        {
                            "type": "input_image",
                            "image_url": "data:"
                            + image["mime"]
                            + ";base64,"
                            + image["data"],
                        },
                    ]
                items.append({"role": row["role"], "content": content})
            body = {
                "model": model,
                "input": items,
                "max_output_tokens": max_tokens,
                "store": False,
            }
            if system:
                body["instructions"] = system
            data, headers = _request(connection, secret, "POST", "/responses", body)
            finish = (
                "stop"
                if data.get("status") == "completed" and not data.get("error")
                else "incomplete"
            )
            text = "".join(
                part.get("text", "")
                for item in data.get("output", [])
                if item.get("type") == "message"
                for part in item.get("content", [])
                if part.get("type") == "output_text"
            )
        elif protocol == "anthropic_messages":
            if image:
                rows[-1]["content"] = [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": image["mime"],
                            "data": image["data"],
                        },
                    },
                    {"type": "text", "text": rows[-1]["content"]},
                ]
            body = {"model": model, "messages": rows, "max_tokens": max_tokens}
            if system:
                body["system"] = system
            data, headers = _request(connection, secret, "POST", "/messages", body)
            reason = data.get("stop_reason")
            finish = "stop" if reason in ("end_turn", "stop_sequence") else "incomplete"
            text = "".join(
                part.get("text", "")
                for part in data.get("content", [])
                if part.get("type") == "text"
            )
        elif protocol == "openai_compatible":
            if image:
                rows[-1]["content"] = [
                    {"type": "text", "text": rows[-1]["content"]},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": "data:" + image["mime"] + ";base64," + image["data"]
                        },
                    },
                ]
            body = {
                "model": model,
                "messages": ([{"role": "system", "content": system}] if system else [])
                + rows,
                "max_tokens": max_tokens,
            }
            data, headers = _request(
                connection, secret, "POST", "/chat/completions", body
            )
            choices = data.get("choices") or []
            if not choices or not isinstance(choices[0], dict):
                raise ProtocolError("Özel API seçimi boş.")
            text = (choices[0].get("message") or {}).get("content")
            finish = choices[0].get("finish_reason")
        else:
            raise ProtocolError("Protokol adaptörü bilinmiyor.")
        usage_meter.observe_response(data, finish_reason=finish)
        usage_meter.observe_limits(provider, model, headers, owner=owner)
        usage_meter.record(
            provider,
            model,
            sent,
            len(text) if isinstance(text, str) else 0,
            "ok" if isinstance(text, str) and text.strip() else "bos",
            owner=owner,
            tokens=usage_meter.tokens_from(data),
        )
        metered = True
        requests_state.check()
        if not isinstance(text, str) or not text.strip():
            raise ProtocolError("Özel API metin yanıtı vermedi.")
        from modules.smart_router import AdapterResponse

        # Finish reason remains explicit even when called outside a capture scope.
        return AdapterResponse(
            text, usage=usage_meter.response_usage(data), finish_reason=finish
        )
    except Exception as exc:
        _record_failure("modules/provider_protocols.py:generation")
        if not metered:
            usage_meter.record(
                provider, model, sent, 0, usage_meter.outcome(exc), owner=owner
            )
        raise


def models(connection, secret):
    from urllib.parse import quote

    out = []
    after = None
    seen = set()
    for _page in range(20):
        path = "/models" + (
            "?limit=100" + ("&after_id=" + quote(after, safe="") if after else "")
            if connection["protocol"] == "anthropic_messages"
            else ""
        )
        data, _headers = _request(connection, secret, "GET", path)
        rows = data.get("data")
        if not isinstance(rows, list):
            raise ProtocolError("API model listesi okunamadı.")
        out.extend(
            {"id": row["id"], "name": row.get("display_name") or row["id"]}
            for row in rows
            if isinstance(row, dict)
            and isinstance(row.get("id"), str)
            and 0 < len(row["id"]) <= 150
        )
        if not data.get("has_more") or connection["protocol"] != "anthropic_messages":
            return out[:2000]
        after = data.get("last_id")
        if not isinstance(after, str) or not after or after in seen:
            raise ProtocolError("API model sayfalaması geçersiz.")
        seen.add(after)
    raise ProtocolError("API model listesi 20 sayfa sınırını aştı.")
