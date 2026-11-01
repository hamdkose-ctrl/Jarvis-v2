from __future__ import annotations

import re
from pathlib import Path


def read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    Path(path).write_text(text, encoding="utf-8", newline="\n")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one exact match, found {count}: {old[:80]!r}")
    write(path, text.replace(old, new, 1))


def sub_once(path: str, pattern: str, repl: str) -> None:
    text = read(path)
    new, count = re.subn(pattern, repl, text, count=1, flags=re.S | re.M)
    if count != 1:
        raise SystemExit(f"{path}: expected one regex match, found {count}: {pattern[:100]!r}")
    write(path, new)


# ---------------------------------------------------------------- brain_understanding
path = "modules/brain_understanding.py"
replace_once(
    path,
    '    "dosyalar",\n    "dosyaları",\n    "dosyalari",\n    "word",\n',
    '    "dosyalar",\n    "dosyaları",\n    "dosyalari",\n    "dosyalarım",\n    "dosyalarim",\n    "dosyalarımı",\n    "dosyalarimi",\n    "word",\n',
)
replace_once(
    path,
    '    if _has_file_domain(text) and _has_read_like_command(text):\n        return "files.read"\n',
    '    if _file_operation(text) is not None:\n        return "files.read"\n',
)

new_file_block = r'''FILE_SUMMARIZE = "summarize"
FILE_ANALYZE = "analyze"
FILE_OPEN = "open"
FILE_LOCATE = "locate"
FILE_LIST = "list"
FILE_COMPARE = "compare"
FILE_TRANSLATE = "translate"
FILE_CONVERT = "convert"
FILE_TARGET_UNRESOLVED = "file target unresolved"
FILE_TRANSLATION_TARGET_MISSING = "file translation target missing"
FILE_CONVERSION_FORMAT_MISSING = "file conversion format missing"
_FILE_TARGET_REQUIRED = frozenset({FILE_SUMMARIZE, FILE_ANALYZE, FILE_OPEN, FILE_LOCATE, FILE_TRANSLATE, FILE_CONVERT})
_FILE_LANGUAGE_PATTERNS = (
    (re.compile(r"(?<!\w)türkçe(?:ye|ya|e|a)?\s+(?:diline\s+)?çevir\w*(?!\w)"), "Türkçe"),
    (re.compile(r"(?<!\w)ingilizce(?:ye|ya|e|a)?\s+(?:diline\s+)?çevir\w*(?!\w)"), "İngilizce"),
    (re.compile(r"(?<!\w)almanca(?:ya|ye|a|e)?\s+(?:diline\s+)?çevir\w*(?!\w)"), "Almanca"),
    (re.compile(r"(?<!\w)fransızca(?:ya|ye|a|e)?\s+(?:diline\s+)?çevir\w*(?!\w)"), "Fransızca"),
    (re.compile(r"(?<!\w)arapça(?:ya|ye|a|e)?\s+(?:diline\s+)?çevir\w*(?!\w)"), "Arapça"),
    (re.compile(r"(?<!\w)rusça(?:ya|ye|a|e)?\s+(?:diline\s+)?çevir\w*(?!\w)"), "Rusça"),
    (re.compile(r"(?<!\w)ispanyolca(?:ya|ye|a|e)?\s+(?:diline\s+)?çevir\w*(?!\w)"), "İspanyolca"),
)
_FILE_FORMAT_RE = re.compile(
    r"(?<!\w)(pdf|excel|xlsx|word|docx)(?:['’]?(?:e|a|ye|ya))?(?:\s+formatına)?\s+dönüştür\w*(?!\w)"
)


def _file_language(text: str) -> str | None:
    for pattern, label in _FILE_LANGUAGE_PATTERNS:
        if pattern.search(text):
            return label
    return None


def _file_format(text: str) -> str | None:
    match = _FILE_FORMAT_RE.search(text)
    if match is None:
        return None
    return {"excel": "xlsx", "word": "docx"}.get(match.group(1), match.group(1))


def _file_operation(text: str) -> str | None:
    """One bounded natural-language file operation; multi-action requests stay with the step/legacy path."""
    if not _has_file_domain(text) or _is_meta_language(text) or _is_literal_command_usage(text):
        return None
    operations: list[str] = []
    if _contains_command_token(text, ("karşılaştır", "karsilastir")):
        operations.append(FILE_COMPARE)
    if re.search(r"(?<!\w)(?:dönüştür|donustur)\w*(?!\w)", text):
        operations.append(FILE_CONVERT)
    if re.search(r"(?<!\w)(?:çevir|cevir)\w*(?!\w)", text):
        operations.append(FILE_TRANSLATE)
    if re.search(r"(?<!\w)(?:analiz\s+et\w*|incele\w*)(?!\w)", text):
        operations.append(FILE_ANALYZE)
    if _contains_command_token(text, ("özetle", "ozetle")):
        operations.append(FILE_SUMMARIZE)
    if _contains_command_token(text, ("aç", "ac")):
        operations.append(FILE_OPEN)
    if _contains_command_token(text, ("bul",)):
        operations.append(FILE_LOCATE)
    if _contains_command_token(text, ("listele",)):
        operations.append(FILE_LIST)
    if _contains_command_token(text, ("göster", "goster")):
        plural = _contains_domain_token(text, ("dosyalar", "dosyaları", "dosyalari", "dosyalarım", "dosyalarim", "dosyalarımı", "dosyalarimi"))
        operations.append(FILE_LIST if plural else FILE_LOCATE)
    # Same operation may be expressed twice; different operations mean a compound request.
    unique = tuple(dict.fromkeys(operations))
    return unique[0] if len(unique) == 1 else None


def _file_arguments(text: str, references: tuple[ContextReference, ...]) -> dict[str, object]:
    """Operation + target proposal. Paths come ONLY from resolved file references, never raw text."""
    operation = _file_operation(text)
    if operation is None:
        return {}
    if operation == FILE_LIST:
        return {"operation": FILE_LIST}
    files = [ref for ref in references if ref.kind == "file"]
    if operation == FILE_COMPARE:
        paths = []
        for ref in files:
            value = ref.provenance.get("path")
            if isinstance(value, str) and value.strip() and value not in paths:
                paths.append(value)
        return {"operation": FILE_COMPARE, "paths": tuple(paths)} if 2 <= len(paths) <= 10 else {}
    if len(files) != 1:
        return {}
    path = files[0].provenance.get("path")
    if not isinstance(path, str) or not path.strip():
        return {}
    row: dict[str, object] = {"operation": operation, "path": path}
    if operation == FILE_TRANSLATE:
        target = _file_language(text)
        if target is None:
            return {}
        row["target"] = target
    elif operation == FILE_CONVERT:
        fmt = _file_format(text)
        if fmt is None:
            return {}
        row["format"] = fmt
    return row


'''
sub_once(
    path,
    r'FILE_SUMMARIZE = "summarize"\n.*?(?=_LEVEL_WORDS = \{)',
    new_file_block,
)
replace_once(
    path,
    '    notes_read_request = False if (context_control or topic_change or correction) else _is_notes_read_request(normalized)\n    ambiguities = _ambiguity_for_references(normalized, references)\n',
    '    notes_read_request = False if (context_control or topic_change or correction) else _is_notes_read_request(normalized)\n    file_operation = None if (context_control or topic_change or correction) else _file_operation(normalized)\n    ambiguities = _ambiguity_for_references(normalized, references)\n',
)
replace_once(
    path,
    '    elif (not ambiguities and not context_control and _asks_file_summary(normalized)\n          and not any(ref.kind == "file" for ref in references)):\n        # A file summary with no resolved file must ask; Core never guesses a target from raw text.\n        ambiguities = (FILE_TARGET_UNRESOLVED,)\n',
    '    elif not ambiguities and not context_control and file_operation is not None:\n        file_refs = [ref for ref in references if ref.kind == "file"]\n        if file_operation in _FILE_TARGET_REQUIRED and len(file_refs) != 1:\n            ambiguities = (FILE_TARGET_UNRESOLVED,)\n        elif file_operation == FILE_COMPARE and not 2 <= len(file_refs) <= 10:\n            ambiguities = (FILE_TARGET_UNRESOLVED,)\n        elif file_operation == FILE_TRANSLATE and _file_language(normalized) is None:\n            ambiguities = (FILE_TRANSLATION_TARGET_MISSING,)\n        elif file_operation == FILE_CONVERT and _file_format(normalized) is None:\n            ambiguities = (FILE_CONVERSION_FORMAT_MISSING,)\n',
)
replace_once(
    path,
    '    elif (level is not None or notes_read_request or note_write is not None or weather_request or research_request\n          or translation is not None or _looks_like_capability(normalized)):\n',
    '    elif (level is not None or notes_read_request or note_write is not None or weather_request or research_request\n          or translation is not None or file_operation is not None or _looks_like_capability(normalized)):\n',
)
replace_once(
    path,
    '    elif FILE_TARGET_UNRESOLVED in ambiguities:\n        reason_codes.append("FILE_TARGET_UNRESOLVED")\n    elif NOTE_TARGET_UNRESOLVED in ambiguities:\n',
    '    elif FILE_TARGET_UNRESOLVED in ambiguities:\n        reason_codes.append("FILE_TARGET_UNRESOLVED")\n    elif FILE_TRANSLATION_TARGET_MISSING in ambiguities:\n        reason_codes.append("FILE_TRANSLATION_TARGET_MISSING")\n    elif FILE_CONVERSION_FORMAT_MISSING in ambiguities:\n        reason_codes.append("FILE_CONVERSION_FORMAT_MISSING")\n    elif NOTE_TARGET_UNRESOLVED in ambiguities:\n',
)

# ---------------------------------------------------------------- brain_core_map
path = "modules/brain_core_map.py"
replace_once(
    path,
    '    FILE_SUMMARIZE,\n    FILE_TARGET_UNRESOLVED,\n',
    '    FILE_ANALYZE,\n    FILE_COMPARE,\n    FILE_CONVERSION_FORMAT_MISSING,\n    FILE_CONVERT,\n    FILE_LIST,\n    FILE_LOCATE,\n    FILE_OPEN,\n    FILE_SUMMARIZE,\n    FILE_TARGET_UNRESOLVED,\n    FILE_TRANSLATE,\n    FILE_TRANSLATION_TARGET_MISSING,\n',
)
new_core_file = r'''def _validated_file_path(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip() or "\x00" in value or not os.path.isabs(value):
        return None
    try:
        from pathlib import Path
        from modules import nxapi
        target = Path(value)
        if not target.is_file() or nxapi.allowed(target) is None:
            return None
    except Exception:
        _record_failure("modules/brain_core_map.py:file_args")
        return None
    return value


_FILE_OPS = frozenset({FILE_SUMMARIZE, FILE_ANALYZE, FILE_OPEN, FILE_LOCATE, FILE_LIST, FILE_COMPARE, FILE_TRANSLATE, FILE_CONVERT})
_FILE_LANGUAGES = frozenset({"Türkçe", "İngilizce", "Almanca", "Fransızca", "Arapça", "Rusça", "İspanyolca"})
_FILE_FORMATS = frozenset({"xlsx", "docx", "pdf"})


def _file_args(arguments: Mapping[str, Any]) -> dict[str, Any] | None:
    """Core validates exact operation + resolved path(s); no raw-text target selection is allowed here."""
    operation = arguments.get("operation")
    if operation not in _FILE_OPS:
        return None
    if operation == FILE_LIST:
        return {"operation": FILE_LIST}
    if operation == FILE_COMPARE:
        paths = arguments.get("paths")
        if not isinstance(paths, (list, tuple)) or not 2 <= len(paths) <= 10:
            return None
        validated = tuple(_validated_file_path(value) for value in paths)
        if any(value is None for value in validated) or len(set(validated)) != len(validated):
            return None
        return {"operation": FILE_COMPARE, "paths": validated}
    path = _validated_file_path(arguments.get("path"))
    if path is None:
        return None
    result: dict[str, Any] = {"operation": operation, "path": path}
    if operation == FILE_TRANSLATE:
        target = arguments.get("target")
        if target not in _FILE_LANGUAGES:
            return None
        result["target"] = target
    elif operation == FILE_CONVERT:
        fmt = arguments.get("format")
        if fmt not in _FILE_FORMATS:
            return None
        result["format"] = fmt
    return result


'''
sub_once(path, r'def _file_args\(arguments: Mapping\[str, Any\]\).*?(?=def _reminder_args)', new_core_file)
replace_once(
    path,
    '    # Only the summarize operation on a Brain-resolved file; other files.read operations stay\n    # on the legacy owner (PARTIAL_CORE_HINTS) because they carry no validated operation.\n    "files.read": ("doc_summary", _file_args),\n',
    '    # Natural-language file target/operation is Brain-proposed and Core-validated; exact UI file buttons remain a front gate.\n    "files.read": ("file_action", _file_args),\n',
)
replace_once(
    path,
    '    "files.read": "engine_commands._file_command + legacy handler (göster/aç/bul/listele/karşılaştır)",\n',
    '',
)
replace_once(
    path,
    '    if FILE_TARGET_UNRESOLVED in ambiguities:\n        return "Hangi dosyayı özetleyeyim? Dosya adını yaz ya da dosyayı sohbete ekle."\n',
    '    if FILE_TARGET_UNRESOLVED in ambiguities:\n        return "Hangi dosyayı veya dosyaları kastettiğini netleştir; dosya adını yaz ya da dosyayı sohbete ekle."\n    if FILE_TRANSLATION_TARGET_MISSING in ambiguities:\n        return "Dosyayı hangi dile çevireyim? Örneğin İngilizce veya Türkçe de."\n    if FILE_CONVERSION_FORMAT_MISSING in ambiguities:\n        return "Dosyayı hangi formata dönüştüreyim? Excel, Word veya PDF de."\n',
)

# ---------------------------------------------------------------- brain_entry
path = "modules/brain_entry.py"
replace_once(
    path,
    '    if plan is not None and plan[0] in {"notes_read", "notes_write"}:\n        ident = plan[1].get("id")\n        # A note effect/read may target only an id Brain resolved for THIS request, never an arbitrary string.\n        if ident is not None and ident not in {ref.id for ref in semantic.references if ref.kind == "note"}:\n            return None\n    if plan is not None and plan[0] == "translate" and not _translate_source_is_brains(entry, plan[1]):\n',
    '    if plan is not None and plan[0] in {"notes_read", "notes_write"}:\n        ident = plan[1].get("id")\n        # A note effect/read may target only an id Brain resolved for THIS request, never an arbitrary string.\n        if ident is not None and ident not in {ref.id for ref in semantic.references if ref.kind == "note"}:\n            return None\n    if plan is not None and plan[0] == "file_action":\n        allowed = {str(ref.provenance.get("path")) for ref in semantic.references\n                   if ref.kind == "file" and isinstance(ref.provenance.get("path"), str)}\n        path = plan[1].get("path")\n        paths = plan[1].get("paths")\n        if path is not None and path not in allowed:\n            return None\n        if paths is not None and (not isinstance(paths, (list, tuple)) or any(value not in allowed for value in paths)):\n            return None\n    if plan is not None and plan[0] == "translate" and not _translate_source_is_brains(entry, plan[1]):\n',
)
sub_once(
    path,
    r'def _file_access_refusal\(entry: EntryResult\) -> str \| None:\n.*?(?=\ndef handoff)',
    '''def _file_access_refusal(entry: EntryResult) -> str | None:\n    """A resolved file proposal rejected by Core/fence fails closed instead of legacy target guessing."""\n    if entry.state_gate.matched or (entry.fast_gate is not None and entry.fast_gate.matched):\n        return None\n    semantic = entry.understanding\n    if semantic is None or semantic.request_kind is not RequestKind.CAPABILITY or semantic.capability_hint != "files.read":\n        return None\n    operation = semantic.arguments.get("operation")\n    if operation in (None, "list"):\n        return None\n    if "path" not in semantic.arguments and "paths" not in semantic.arguments:\n        return None\n    if core_plan(entry) is not None:\n        return None\n    return "Bu dosyaya erişemiyorum (izinli klasörlerin dışında, bulunamıyor veya hedef doğrulanamadı); işlem başlatılmadı."\n\n''',
)

# ---------------------------------------------------------------- brain_precedence
path = "modules/brain_precedence.py"
replace_once(
    path,
    '        if plan is not None and plan[0] in {"notes_read", "notes_write"}:\n            return None\n        # A reminder plan is executed BY the planner at its own creation slot with the Core-validated\n',
    '        if plan is not None and plan[0] in {"notes_read", "notes_write", "file_action"}:\n            return None\n        # A reminder plan is executed BY the planner at its own creation slot with the Core-validated\n',
)
replace_once(
    path,
    '    return {\n        "file_command": lambda: runtime._file_command(command),\n',
    '    def extra_commands():\n        # The exact quoted-path UI file_command above remains authoritative. For a canonical natural-language\n        # file_action, do not let the later legacy files.handle/_resolve_doc chain reinterpret the target.\n        if plan is not None and plan[0] == "file_action":\n            return None\n        return runtime._extra_commands(command, lowered)\n\n    return {\n        "file_command": lambda: runtime._file_command(command),\n',
)
replace_once(path, '        "extra_commands": lambda: runtime._extra_commands(command, lowered),\n', '        "extra_commands": extra_commands,\n')

# ---------------------------------------------------------------- engine_intents
path = "modules/engine_intents.py"
insert = r'''        case "file_action":
            from pathlib import Path
            from modules import nxapi
            operation = str(a.get("operation") or "")
            if operation == "list":
                rows = nxapi.list_files(limit=25).get("files", [])
                if not rows:
                    return "İzinli klasörlerinde dosya bulamadım."
                return "Dosyalar:\n" + "\n".join(
                    f"- {row.get('name') or Path(str(row.get('path') or '')).name} — {row.get('where') or row.get('folder') or ''}".rstrip(" —")
                    for row in rows
                )

            def exact(value):
                if not isinstance(value, str):
                    return None
                checked = nxapi.allowed(value)
                return checked if checked is not None and checked.is_file() else None

            if operation == "compare":
                raw_paths = a.get("paths")
                if not isinstance(raw_paths, (list, tuple)):
                    return "Karşılaştırılacak dosyalar doğrulanamadı."
                paths = [exact(value) for value in raw_paths]
                if any(value is None for value in paths):
                    return "Karşılaştırılacak dosyalardan biri artık erişilebilir değil."
                from modules import workbench
                return workbench.handle(runtime.profile.slug, [str(value) for value in paths], "karşılaştır")

            path = exact(a.get("path"))
            if path is None:
                return "Bu dosyaya artık erişemiyorum; işlem başlatılmadı."
            path_s = str(path)
            if operation == "summarize":
                result = runtime.docs.summarize(path_s)
                runtime._session().last_doc = (result, path_s, "ozet")
                return result + "\n\nDosya olarak almak istersen çıktı al de."
            if operation == "analyze":
                result = runtime.docs.insights(path_s, "")
                runtime._session().last_doc = (result, path_s, "analiz")
                return result + "\n\nDosya olarak almak istersen çıktı al de."
            if operation == "open":
                nxapi.open_path(path_s)
                return f"{path.name} dosyasını açtım."
            if operation == "locate":
                row = nxapi.describe_file(path_s) or {}
                where = row.get("where") or row.get("folder") or str(path.parent)
                return f"{path.name} — {where}"
            if operation == "translate":
                return runtime._translate_file(path_s, str(a.get("target") or ""))
            if operation == "convert":
                fmt = str(a.get("format") or "")
                saved = runtime.output.convert_document(path_s, fmt)
                return (f"Dosyayı {fmt.upper()} formatında kaydettim: {saved['path']}" + ('\n' + saved['note'] if saved['note'] else '')) if saved else "Dönüştürme iptal edildi."
            return "Bu dosya işlemi Core tarafından doğrulanmadı."

'''
replace_once(path, '        case "doc_summary":\n', insert + '        case "doc_summary":\n')

# ---------------------------------------------------------------- old architecture tests reflect the new canonical intent
path = "tests/test_brain_b3b.py"
replace_once(
    path,
    '        # B3c-1: the only document intent Core may plan is doc_summary, from a validated resolved path.\n        self.assertEqual({i for i, _ in brain_core_map.CORE_INTENTS.values()} & {"doc_summary", "doc_insight", "doc_convert", "doc_translate"},\n                         {"doc_summary"})\n',
    '        # Final file cutover: normal Brain file operations use one Core file_action; old doc_* stay legacy/Live only.\n        intents = {i for i, _ in brain_core_map.CORE_INTENTS.values()}\n        self.assertIn("file_action", intents)\n        self.assertFalse(intents & {"doc_summary", "doc_insight", "doc_convert", "doc_translate"})\n',
)

path = "tests/test_brain_b3c1.py"
replace_once(
    path,
    '            self.assertEqual(brain_core_map.core_plan("files.read", {"operation": "summarize", "path": good}),\n                             ("doc_summary", {"path": good}))\n',
    '            self.assertEqual(brain_core_map.core_plan("files.read", {"operation": "summarize", "path": good}),\n                             ("file_action", {"operation": "summarize", "path": good}))\n',
)
replace_once(path, '        self.assertEqual(dispatch.call_args[0][1], "doc_summary")\n        self.assertEqual(dispatch.call_args[0][2], {"path": str(self.file)})\n',
             '        self.assertEqual(dispatch.call_args[0][1], "file_action")\n        self.assertEqual(dispatch.call_args[0][2], {"operation": "summarize", "path": str(self.file)})\n')
replace_once(path, '            self.assertNotEqual(call.args[1], "doc_summary")\n', '            self.assertNotEqual(call.args[1], "file_action")\n')

# ---------------------------------------------------------------- roadmap: in-progress truth, not completion claim yet
path = "docs/Jarvis_Yol_Haritasi.md"
text = read(path)
pattern = r'^- 🔄 \(PR7 Closeout-B3c-1\).*?$'
replacement = ('- 🟡 (#488 / PR7 Closeout-B3c-1+final-files) `[1✓ 2🔄 3✓ 4✗]` Normal Brain file yolu tek `file_action` Core intentine taşınıyor: '
               '`özetle/analiz et/aç/bul/listele/karşılaştır/çevir/dönüştür` operasyonu Understanding tarafından önerilir; hedef path(ler) yalnız Candidate Builder + Reference Resolver referansından gelir; Core operation/path/format/dil ve `nxapi.allowed` sınırını yeniden doğrular. Canonical yol `_resolve_doc` ile hedefi tekrar seçmez. Exact tırnaklı UI `_file_command` deterministic front gate olarak korunur. Bu satır #488 exact-head Windows CI + gerçek PC watcher PASS olmadan tamamlandı sayılmaz.')
new, count = re.subn(pattern, replacement, text, count=1, flags=re.M)
if count != 1:
    raise SystemExit(f"roadmap B3c-1 line expected once, got {count}")
write(path, new)

print("PR488 bounded implementation patch applied")
