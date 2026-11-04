"""Kapalı uygulama kimliği tablosu ve yazım toleranslı hedef çözümlemesi.

Saf veri/kural modülü: uygulama açmaz, pencere okumaz, kurulu-uygulama taraması yapmaz.
`system_control` yürütme için aynı tabloyu kullanır; canonical Understanding hedefi yalnız bu
kapalı kümeden doğrular.
"""
from __future__ import annotations

import re

from modules import typo

# Sabit kısayollar. Bunların dışında yalnızca Başlat menüsünde kurulu görünen uygulamalar açılır
# (serbest komut çalıştırılmaz; komut enjeksiyonu olmaz).
# Yeni uygulama eklemek için: "söylenen ad": "çalıştırılacak program" satırı ekle.
APPS = {
    "chrome": "chrome",
    "krom": "chrome",
    "google chrome": "chrome",
    "edge": "msedge",
    "tarayıcı": "msedge",
    "notepad": "notepad",
    "not defteri": "notepad",
    "notdefteri": "notepad",
    "hesap makinesi": "calc",
    "calculator": "calc",
    "calc": "calc",
    "calculatorapp": "calc",
    "paint": "mspaint",
    "excel": "excel",
    "word": "winword",
    "powerpoint": "powerpnt",
    "power point": "powerpnt",
    "vs code": "code",
    "vscode": "code",
    "visual studio code": "code",
    "outlook": "outlook",
    "teams": "ms-teams",
    "dosya gezgini": "explorer",
}

_ALIAS_SUFFIX = re.compile(r"['’]?(?:y?[ıiuü]|y?[ea]|n[ıiuü])$")


def verified_alias(target: str) -> str | None:
    """Konuşulan hedefi tek kesin sabit kimliğe çözer; çoklu ya da yoksa None.

    Önce katlanmış tam eşleşme, yoksa tek düzenleme uzaklığı aranır."""
    base = _ALIAS_SUFFIX.sub("", target.strip().casefold())
    forms = {form for form in (typo.fold(target), typo.fold(base)) if form}
    exact = [alias for alias in APPS if len(typo.fold(alias)) >= 4 and typo.fold(alias) in forms]
    if exact:
        return exact[0] if len(exact) == 1 else None
    near = [alias for alias in APPS
            if len(typo.fold(alias)) >= 4 and any(typo.one_edit(form, typo.fold(alias)) for form in forms)]
    return near[0] if len(near) == 1 else None
