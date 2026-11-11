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

## Additional cooperative writers in this PR

`file_ops.undo` now rechecks each receipt's source/old path inside the
same OS claim as forward rename/move/create operations before changing it.
`file_worker_extensions.patch_text` performs its bounded validation,
read and write under the file claim; `create_pptx` (including injected
writer) reserves the exact destination before saving. Claims are only
held while changing local files. Other report/media writer adapters remain
outside this package. An inode value of zero is not trusted as a physical
identity to avoid blocking unrelated files on some Windows filesystems.
