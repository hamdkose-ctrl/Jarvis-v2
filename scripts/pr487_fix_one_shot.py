from pathlib import Path


def replace_count(path, old, new, expected=1):
    p = Path(path)
    text = p.read_text(encoding='utf-8')
    count = text.count(old)
    if count != expected:
        raise SystemExit(f'{path}: expected {expected} match(es), found {count}: {old[:80]!r}')
    p.write_text(text.replace(old, new), encoding='utf-8')

# Scope containment: oku/say are notes-only, not global capability/read verbs.
replace_count('modules/brain_understanding.py',
'''    "göster",\n    "goster",\n    "oku",\n    "say",\n    "aç",''',
'''    "göster",\n    "goster",\n    "aç",''', expected=2)
replace_count('modules/brain_understanding.py',
'''def _capability_hint(text: str, temporal_need: TemporalNeed) -> str | None:\n    if _is_meta_language(text) or _is_literal_command_usage(text):\n        return None\n    if _note_write_request(text) is not None:\n        return "notes.write"\n    if _contains_domain_token(text, _NOTE_DOMAIN_TOKENS) and _has_read_like_command(text):\n        return "notes.read"''',
'''def _is_notes_read_request(text: str) -> bool:\n    return _contains_domain_token(text, _NOTE_DOMAIN_TOKENS) and _contains_command_token(text, _NOTES_READ_VERBS)\n\n\ndef _capability_hint(text: str, temporal_need: TemporalNeed) -> str | None:\n    if _is_meta_language(text) or _is_literal_command_usage(text):\n        return None\n    if _note_write_request(text) is not None:\n        return "notes.write"\n    if _is_notes_read_request(text):\n        return "notes.read"''')
replace_count('modules/brain_understanding.py',
'''    note_write = None if (context_control or topic_change or correction) else _note_write_request(normalized)\n    ambiguities = _ambiguity_for_references(normalized, references)''',
'''    note_write = None if (context_control or topic_change or correction) else _note_write_request(normalized)\n    notes_read_request = False if (context_control or topic_change or correction) else _is_notes_read_request(normalized)\n    ambiguities = _ambiguity_for_references(normalized, references)''')
replace_count('modules/brain_understanding.py',
'''    elif level is not None or weather_request or research_request or translation is not None or _looks_like_capability(normalized):\n        request_kind = RequestKind.CAPABILITY''',
'''    elif (level is not None or notes_read_request or note_write is not None or weather_request or research_request\n          or translation is not None or _looks_like_capability(normalized)):\n        request_kind = RequestKind.CAPABILITY''')

# Canonical notes plans must not be reinterpreted by the legacy planner resolver/UI gate.
replace_count('modules/brain_precedence.py',
'''        if plan is not None and plan[0] == "notes_read":\n            return None''',
'''        if plan is not None and plan[0] in {"notes_read", "notes_write"}:\n            return None''', expected=2)

# Stable-ID fence: Core may execute only a note id resolved for this request.
replace_count('modules/brain_entry.py',
'''    if plan is not None and plan[0] == "notes_read" and plan[1].get("which") == "one":\n        # The id must be one of the note references Brain resolved for THIS request, not any string.\n        if plan[1]["id"] not in {ref.id for ref in semantic.references if ref.kind == "note"}:\n            return None''',
'''    if plan is not None and plan[0] in {"notes_read", "notes_write"}:\n        ident = plan[1].get("id")\n        # A note effect/read may target only an id Brain resolved for THIS request, never an arbitrary string.\n        if ident is not None and ident not in {ref.id for ref in semantic.references if ref.kind == "note"}:\n            return None''')

# The only intended B3b change from this PR is the notes read synonym.
replace_count('tests/test_brain_b3b.py',
'''IMPROVED = {"yarın hava nasıl olacak", "bana hatırlat", "belgeyi özetle", "ankara'da hava nasıl"}''',
'''IMPROVED = {"yarın hava nasıl olacak", "bana hatırlat", "belgeyi özetle", "ankara'da hava nasıl", "notlarımı oku"}''')

Path('.github/workflows/pr487-fix-one-shot.yml').unlink(missing_ok=True)
Path('scripts/pr487_fix_one_shot.py').unlink(missing_ok=True)
