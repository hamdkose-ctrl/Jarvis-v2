# BRAIN-07 — Cooperative file-effect path ownership

This package integrates the existing OS claim primitive with both
`file_ops.handle` (spoken/typed) and `file_ops.execute_typed` (Core typed
action) for **move, rename, create** mutations. Each effect acquires
canonical path-based resource keys and, when present, the existing inode
identity as a second alias, before validating the source and acting.

Claims for the old source and intended target are acquired in canonical
sorted order using a nonblocking OS lock. A collision leaves the file
untouched, while independent filenames remain available. The target
directory/file permission gate is unchanged. New text files use exclusive
create (`'x'`) rather than overwriting a name discovered concurrently.

**Limits:** claims coordinate cooperating Jarvis `file_ops` paths sharing
the same `DATA_DIR` only. Legacy undo log and other writer adapters
(`writer`, `file_worker_extensions.patch_text`, `media`) do not yet
participate and require a follow-up integration before general file
resource coverage or BRAIN-07 closeout. External programs may still edit
files; these locks are not an OS-level filesystem transaction.

Acceptance: exact-head Windows CI and matching PC watcher PASS.
