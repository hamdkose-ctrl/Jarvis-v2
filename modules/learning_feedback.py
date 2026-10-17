"""Deterministic learning from explicit assistant-behaviour feedback.

Only direct, durable instructions about how Jarvis should respond are promoted to
profile rules. Facts, one-off tasks and ambiguous complaints stay ordinary chat.
"""
from __future__ import annotations
import re


def _clean(text):
    return ' '.join(str(text or '').split()).strip(' .!?;:\"\'“”')


def _fold(text):
    return _clean(text).casefold().replace('ı','i').replace('\u0307','')


def rules_from_feedback(text):
    """Return a small set of explicit, reusable behaviour rules."""
    raw=_clean(text);low=_fold(raw)
    if not raw or len(raw)>1000:return []
    rules=[]

    # Strong correction used in normal conversation: do not reflexively agree.
    if (re.search(r'\bhakli(?:sin|yim|olamam|degilim)?\b',low) and re.search(r'\b(?:deme|hep|surekli|yanlis)\b',low)) or \
       re.search(r'\b(?:yanlissam|yanlissam|yanlissa|yanlis\s+olursam).{0,35}\b(?:soyle|belirt|duzelt)\b',low):
        rules.append('Kullanıcının iddiasını otomatik onaylama; kanıtla değerlendir, yanlışsa açıkça söyle ve nedenini belirt.')

    # “Bana sürekli X deme” is a direct response-style instruction.
    m=re.search(r'\bbana\s+(?:(?:hep|surekli)\s+)?(.{1,90}?)\s+deme\b',low)
    if m:
        phrase=_clean(m.group(1))
        if phrase and not re.search(r'\b(?:sifre|parola|token|anahtar|iban|kart)\b',phrase,re.I):
            rules.append('Kullanıcıya gereksiz yere veya otomatik olarak “'+phrase+'” deme.')

    # Explicit “bana X yapma” feedback, but not a one-off external action.
    m=re.search(r'\bbana\s+(.{1,120}?)\s+yapma\b',low)
    if m:
        behaviour=_clean(m.group(1))
        if behaviour and not re.search(r'\b(?:gonder|sil|kapat|ac|ara|indir|yukle|ode|satinal)\b',behaviour):
            rules.append('Kullanıcıya yönelik şu davranışı tekrarlama: '+behaviour+'.')

    # Direct preference about files/results: keep delivery in chat unless explicitly requested.
    if re.search(r'\bdosya(?:ya| olarak)?\b',low) and re.search(r'\b(?:gerek yok|istemedikce|istemezsem|sadece istersem)\b',low):
        rules.append('Kullanıcı açıkça dosya istemedikçe normal bilgi ve araştırma sonucunu doğrudan sohbette teslim et.')

    out=[]
    for rule in rules:
        if rule not in out:out.append(rule)
    return out[:3]


def capture(profile,text):
    """Persist explicit behavioural feedback through the existing rule store."""
    rules=rules_from_feedback(text)
    if not rules:return []
    from modules import learning
    stored=[]
    before={learning._low(r) for r in learning.rules(profile)}
    for rule in rules:
        learning.add_rule(profile,rule)
        if learning._low(rule) not in before:
            stored.append(rule);before.add(learning._low(rule))
    return stored
