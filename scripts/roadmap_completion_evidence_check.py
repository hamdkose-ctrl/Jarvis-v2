"""Roadmap'te yeni tamamlanan maddeler icin deterministik kanit kapisi.

Bu kontrol yalniz PR'da YENI veya yeniden `✅` yapilan satirlari zorlar. Main'de
zaten tamamlanmis eski maddeleri geriye donuk kirmak istemez.

Yeni bir tamamlanma satirinin ardindaki ilk bos olmayan satir su bicimde olmalidir:

  Kanıt: PR=#410; SHA=abcdef123456; Contract=#372; Migration=n/a; Wiring=#400;
  Acceptance=watcher-pass@abcdef123456; Cleanup=verified

`SHA` / `Acceptance` test edilmis kod commit'ini gosterir. Sonraki commitler yalniz
dokumantasyon kaniti ekleyebilir; runtime kodu degisirse yeni acceptance gerekir.
"""

from __future__ import annotations

from collections import Counter
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROADMAP_FILE = "docs/Jarvis_Yol_Haritasi.md"
COMPLETION_MARKER = "✅"
EVIDENCE_PREFIX = "Kanıt:"
REQUIRED_FIELDS = (
    "PR",
    "SHA",
    "Contract",
    "Migration",
    "Wiring",
    "Acceptance",
    "Cleanup",
)


def _run(args: list[str], cwd: Path = ROOT):
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(cwd),
    )


def _is_completion_line(line: str) -> bool:
    stripped = line.strip()
    if stripped.startswith("- "):
        return stripped[2:].lstrip().startswith(COMPLETION_MARKER)
    if stripped.startswith("**Durum:"):
        status = stripped[len("**Durum:"):].lstrip()
        return status.startswith(COMPLETION_MARKER)
    return False


def _new_completion_indexes(base_text: str, current_text: str) -> list[int]:
    """Main'de aynen bulunan tamamlanmis satirlari tuket, yenileri dondur."""
    base_completed = Counter(
        line.strip()
        for line in base_text.splitlines()
        if _is_completion_line(line)
    )
    result: list[int] = []
    for index, line in enumerate(current_text.splitlines()):
        if not _is_completion_line(line):
            continue
        key = line.strip()
        if base_completed[key] > 0:
            base_completed[key] -= 1
            continue
        result.append(index)
    return result


def _next_nonempty(lines: list[str], start_index: int) -> tuple[int | None, str | None]:
    for index in range(start_index + 1, len(lines)):
        if lines[index].strip():
            return index, lines[index].strip()
    return None, None


def _parse_evidence(line: str) -> dict[str, str]:
    if not line.startswith(EVIDENCE_PREFIX):
        return {}
    payload = line[len(EVIDENCE_PREFIX):].strip()
    fields: dict[str, str] = {}
    for part in payload.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        key, value = part.split("=", 1)
        fields[key.strip()] = value.strip()
    return fields


def _validate_evidence(fields: dict[str, str]) -> list[str]:
    errors: list[str] = []
    missing = [name for name in REQUIRED_FIELDS if not fields.get(name)]
    if missing:
        errors.append("eksik alanlar: " + ", ".join(missing))
        return errors

    if not re.fullmatch(r"#\d+", fields["PR"]):
        errors.append("PR '#<numara>' biciminde olmali")

    sha = fields["SHA"].lower()
    if not re.fullmatch(r"[0-9a-f]{7,40}", sha):
        errors.append("SHA 7-40 hex karakter olmali")

    if not re.fullmatch(r"#\d+", fields["Contract"]):
        errors.append("Contract '#<numara>' biciminde olmali")

    migration = fields["Migration"]
    if migration != "n/a" and not re.fullmatch(r"#\d+", migration):
        errors.append("Migration '#<numara>' veya n/a olmali")

    if not re.fullmatch(r"#\d+", fields["Wiring"]):
        errors.append("Wiring '#<numara>' biciminde olmali")

    acceptance = fields["Acceptance"].lower()
    match = re.fullmatch(r"watcher-pass@([0-9a-f]{7,40})", acceptance)
    if not match:
        errors.append("Acceptance 'watcher-pass@<SHA>' biciminde olmali")
    elif re.fullmatch(r"[0-9a-f]{7,40}", sha) and match.group(1) != sha:
        errors.append("Acceptance SHA, SHA alaniyla ayni olmali")

    if fields["Cleanup"] not in {"verified", "n/a"}:
        errors.append("Cleanup verified veya n/a olmali")

    return errors


def validate_ci_provenance(
    fields: dict[str, str],
    *,
    pr_number: str,
    pr_head_sha: str,
    is_ancestor: bool,
    changed_paths: list[str],
) -> list[str]:
    """CI baglaminda kanitin gercek PR ve test edilmis kod ancestry'sini dogrula."""
    errors: list[str] = []
    if fields.get("PR") != f"#{str(pr_number).strip()}":
        errors.append("Kanıt PR alanı CI'daki gerçek PR numarasıyla eşleşmeli")
    if not pr_head_sha.strip():
        errors.append("CI PR head SHA bilgisi eksik")
    if not is_ancestor:
        errors.append("Acceptance SHA, güncel PR head commit'inin atası olmalı")

    runtime_changes = []
    for path in changed_paths:
        normalized = str(path).replace("\\", "/").lstrip("./")
        if normalized and not normalized.startswith("docs/"):
            runtime_changes.append(normalized)
    if runtime_changes:
        errors.append(
            "Acceptance sonrasında kod değişikliği var; yeni watcher acceptance gerekli: "
            + ", ".join(runtime_changes)
        )
    return errors


def check_completion_evidence(base_text: str, current_text: str) -> dict:
    lines = current_text.splitlines()
    indexes = _new_completion_indexes(base_text, current_text)
    new_completions: list[str] = []
    missing_evidence: list[str] = []
    invalid_evidence: list[dict] = []
    evidence_records: list[dict] = []

    for index in indexes:
        completion = lines[index].strip()
        new_completions.append(completion)
        _, evidence_line = _next_nonempty(lines, index)
        if evidence_line is None or not evidence_line.startswith(EVIDENCE_PREFIX):
            missing_evidence.append(completion)
            continue
        fields = _parse_evidence(evidence_line)
        evidence_records.append({"completion": completion, "fields": fields})
        errors = _validate_evidence(fields)
        if errors:
            invalid_evidence.append(
                {"completion": completion, "evidence": evidence_line, "errors": errors}
            )

    return {
        "new_completions": new_completions,
        "missing_evidence": missing_evidence,
        "invalid_evidence": invalid_evidence,
        "evidence_records": evidence_records,
        "pass": not missing_evidence and not invalid_evidence,
    }


def _roadmap_on_main(root: Path = ROOT) -> str:
    cp = _run(["git", "show", f"main:{ROADMAP_FILE}"], cwd=root)
    if cp.returncode != 0:
        raise RuntimeError(f"main roadmap okunamadi: {cp.stderr.strip()}")
    return cp.stdout


def _resolve_commit(ref: str, root: Path = ROOT) -> str:
    cp = _run(["git", "rev-parse", f"{ref}^{{commit}}"], cwd=root)
    if cp.returncode != 0 or not cp.stdout.strip():
        raise RuntimeError(f"commit bulunamadi: {ref}")
    return cp.stdout.strip().lower()


def _provenance_from_git(
    fields: dict[str, str], *, pr_number: str, pr_head_sha: str, root: Path = ROOT
) -> list[str]:
    try:
        accepted = _resolve_commit(fields["SHA"], root)
        head = _resolve_commit(pr_head_sha, root)
    except RuntimeError as exc:
        return [str(exc)]

    ancestor_cp = _run(["git", "merge-base", "--is-ancestor", accepted, head], cwd=root)
    is_ancestor = ancestor_cp.returncode == 0

    changed_paths: list[str] = []
    if is_ancestor:
        diff_cp = _run(["git", "diff", "--name-only", f"{accepted}..{head}"], cwd=root)
        if diff_cp.returncode != 0:
            return ["Acceptance sonrası değişiklikler okunamadı"]
        changed_paths = [line.strip() for line in diff_cp.stdout.splitlines() if line.strip()]

    return validate_ci_provenance(
        fields,
        pr_number=pr_number,
        pr_head_sha=head,
        is_ancestor=is_ancestor,
        changed_paths=changed_paths,
    )


def main() -> int:
    current_path = ROOT / ROADMAP_FILE
    if not current_path.is_file():
        print(f"ROADMAP COMPLETION EVIDENCE: {ROADMAP_FILE} bulunamadi")
        return 1

    try:
        base_text = _roadmap_on_main(ROOT)
    except RuntimeError as exc:
        print(f"ROADMAP COMPLETION EVIDENCE: {exc}")
        return 1

    current_text = current_path.read_text(encoding="utf-8", errors="replace")
    result = check_completion_evidence(base_text, current_text)

    if result["missing_evidence"]:
        print("ROADMAP COMPLETION EVIDENCE: yeni tamamlanan maddelerde Kanıt satiri eksik:")
        for item in result["missing_evidence"]:
            print(f"  - {item}")

    if result["invalid_evidence"]:
        print("ROADMAP COMPLETION EVIDENCE: gecersiz Kanıt satirlari:")
        for entry in result["invalid_evidence"]:
            print(f"  - {entry['completion']}")
            for error in entry["errors"]:
                print(f"      {error}")

    if not result["pass"]:
        return 1

    if result["new_completions"]:
        pr_number = os.environ.get("JARVIS_PR_NUMBER", "").strip()
        pr_head_sha = os.environ.get("JARVIS_PR_HEAD_SHA", "").strip()
        if not pr_number or not pr_head_sha:
            print("ROADMAP COMPLETION EVIDENCE: yeni tamamlanma için PR CI bağlamı eksik")
            return 1
        for record in result["evidence_records"]:
            errors = _provenance_from_git(
                record["fields"], pr_number=pr_number, pr_head_sha=pr_head_sha, root=ROOT
            )
            if errors:
                print(f"ROADMAP COMPLETION EVIDENCE: provenance geçersiz: {record['completion']}")
                for error in errors:
                    print(f"  - {error}")
                return 1
        print(
            "ROADMAP COMPLETION EVIDENCE OK: yeni tamamlanan maddelerin "
            "kapanis kanitlari ve acceptance ancestry'si dogrulandi."
        )
    else:
        print("ROADMAP COMPLETION EVIDENCE OK: yeni tamamlanan madde yok.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
