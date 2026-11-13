"""Finance alarm execution owner; Brain/Core exclusively select the operation."""
import re
from modules import finance_alert_store, turkish_text


def _asset(name):
    text = turkish_text.fold(name).strip()
    aliases = {'dolar': ('doviz','USD'), 'euro': ('doviz','EUR'), 'sterlin': ('doviz','GBP'),
               'gram altin': ('altin','GRAM'), 'altin': ('altin','GRAM'), 'bitcoin': ('kripto','BTC'),
               'ethereum': ('kripto','ETH')}
    if text in aliases:
        return aliases[text]
    stock = re.fullmatch(r'([a-z0-9]{1,12}) hissesi', text)
    if stock:
        return 'hisse', stock[1].upper()
    symbol = text.upper()
    from modules import finance
    if symbol in {row[0] for row in finance.CURRENCIES} - {'TRY'}:
        return 'doviz', symbol
    if symbol in finance.COINGECKO_IDS:
        return 'kripto', symbol
    raise ValueError('Geçersiz veya tanınmayan alarm sembolü.')


def _amount(value):
    return format(value, 'g').replace('.', ',')


def _description(rule):
    amount = _amount(rule['value'])
    if rule['op'] in ('above', 'below'):
        direction = 'üstüne çıkınca' if rule['op'] == 'above' else 'altına inince'
        return f"{rule['symbol']} · {amount} TL'nin {direction}"
    direction = 'yükselişte' if rule['op'] == 'pct_up' else 'düşüşte'
    return f"{rule['symbol']} · %{amount} {direction}"


def execute_typed(owner: str, args: dict) -> str:
    """Apply a Core-validated alarm operation via the existing owner store.

    Rules stay in finance_alert_store: no second scheduler, model-owned ID,
    account identity or raw-language interpretation. Deleting by displayed
    ordinal is resolved atomically under the store's existing RLock.
    """
    from modules import requests_state
    requests_state.check()
    operation = args["operation"]
    if operation == "list":
        rows = finance_alert_store.list_rules(owner)
        return ("\n".join(f"{i}. {_description(row)}"
                          for i, row in enumerate(rows, 1))
                or "Kayıtlı finans alarmın yok.")
    if operation == "delete":
        with finance_alert_store._lock:
            rows = finance_alert_store.list_rules(owner)
            index = args["index"]
            if not 1 <= index <= len(rows):
                return "Bu sırada bir finans alarmı yok."
            requests_state.check()
            removed = finance_alert_store.remove_rule(owner, rows[index - 1]["id"])
        return ("Finans alarmı silindi." if removed else
                "Finans alarmı değişti; silme işlemi yapılmadı.")
    if operation != "add":
        return "Finans alarmı işlemi doğrulanmadı; kayıt değişmedi."
    requests_state.check()
    try:
        row = finance_alert_store.add_rule(
            owner, {"kind": args["kind"], "symbol": args["symbol"],
                    "op": args["direction"], "value": args["value"]})
    except ValueError as exc:
        return "Alarm kaydedilmedi: " + str(exc)
    return (f"Alarm kaydedildi: {row['symbol']} {_amount(row['value'])} TL eşiği; "
            "yalnız fiyat bildirimi. Kontrol aralığı yaklaşık 5 dakikadır; "
            "sessiz saatlerde bildirim bekletilir.")
