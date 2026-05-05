"""Validation for workspace paths submitted via /api/set-workspace.

Lives outside ``api/`` so the unit tests can import it without pulling
Flask into scope (the existing test suite intentionally avoids Flask —
see ``tests/test_cli_args.py`` for the convention).

The validation collapses path traversal *and* resolves symlinks via
``os.path.realpath()`` in a single step. Both ``/foo/../bar`` and a
symlink that points outside the intended tree become whatever the
canonical real path is on disk; downstream checks then operate on
that canonical value, not on whatever the caller sent.
"""

from __future__ import annotations

import os

from .path_helpers import expand_tilde_path


class WorkspacePathError(ValueError):
    """Raised when a /api/set-workspace path fails validation.

    Carries a single ``reason`` string suitable for a 400 response body.
    Distinct exception type so the API handler can map it to a 400 while
    letting unexpected exceptions surface as 500.
    """


def _has_cursor_workspace_markers(directory: str) -> bool:
    """Return True iff at least one immediate subdirectory contains state.vscdb.

    Same heuristic /api/validate-path already uses to recognise a Cursor
    workspaceStorage directory. Used here as the final accept gate so that
    a symlink whose realpath happens to leave the user's own data area
    (e.g. /tmp, /etc) is rejected — those locations have no state.vscdb.
    """
    try:
        names = os.listdir(directory)
    except OSError:
        return False
    for name in names:
        full = os.path.join(directory, name)
        try:
            if os.path.isdir(full) and os.path.isfile(os.path.join(full, "state.vscdb")):
                return True
        except OSError:
            continue
    return False


def validate_workspace_path(raw_path: str) -> str:
    """Validate a /api/set-workspace input and return the canonical real path.

    Raises :class:`WorkspacePathError` if the path:
      - is empty / not a string,
      - does not exist after symlink + ``..`` resolution,
      - is not a directory,
      - contains no Cursor workspace markers (no immediate subdir with state.vscdb).

    On success, returns the canonical absolute real path. The caller should
    store that, not the raw input, so subsequent reads resolve through the
    same canonical value.
    """
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise WorkspacePathError("path is required")

    expanded = expand_tilde_path(raw_path)
    # realpath() collapses `..` AND resolves symlinks. Both classes of escape
    # become equivalent to whatever is actually on disk.
    real = os.path.realpath(expanded)

    if not os.path.exists(real):
        raise WorkspacePathError("path does not exist")
    if not os.path.isdir(real):
        raise WorkspacePathError("path is not a directory")
    if not _has_cursor_workspace_markers(real):
        raise WorkspacePathError(
            "path does not look like a Cursor workspaceStorage directory "
            "(no immediate subdirectory contains state.vscdb)"
        )

    return real
