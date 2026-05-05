"""
Regression tests for issue #15 — /api/set-workspace path validation.

Exercises validate_workspace_path() directly. Imports from utils/ to avoid
pulling Flask into scope (tests/test_cli_args.py convention).

Run:
    python -m unittest tests.test_workspace_path_validation -v
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from utils.path_validation import WorkspacePathError, validate_workspace_path


def _make_cursor_workspace_dir(parent: str, name: str = "real-storage") -> str:
    """Create a directory that looks like a Cursor workspaceStorage dir.

    Layout:
      <parent>/<name>/
        ws-001/state.vscdb     ← marker file the validator looks for
    """
    storage = os.path.join(parent, name)
    ws = os.path.join(storage, "ws-001")
    os.makedirs(ws)
    with open(os.path.join(ws, "state.vscdb"), "wb") as f:
        f.write(b"")
    return storage


class TestValidateWorkspacePath(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cursor-validate-test-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    # ─── Happy path ────────────────────────────────────────────────

    def test_accepts_directory_with_cursor_marker(self):
        storage = _make_cursor_workspace_dir(self.tmp)
        result = validate_workspace_path(storage)
        self.assertEqual(result, os.path.realpath(storage))

    def test_returns_canonical_path_collapsing_dotdot(self):
        # /tmp/<x>/real-storage/../real-storage  → /tmp/<x>/real-storage
        storage = _make_cursor_workspace_dir(self.tmp)
        traversal_input = os.path.join(storage, "..", os.path.basename(storage))
        result = validate_workspace_path(traversal_input)
        self.assertEqual(result, os.path.realpath(storage))
        self.assertNotIn("..", result)

    # ─── Hard rejects ──────────────────────────────────────────────

    def test_rejects_empty_string(self):
        with self.assertRaises(WorkspacePathError) as ctx:
            validate_workspace_path("")
        self.assertIn("required", str(ctx.exception))

    def test_rejects_whitespace_only(self):
        with self.assertRaises(WorkspacePathError):
            validate_workspace_path("   \t  ")

    def test_rejects_non_string(self):
        with self.assertRaises(WorkspacePathError):
            validate_workspace_path(None)  # type: ignore[arg-type]

    def test_rejects_non_existent_path(self):
        bogus = os.path.join(self.tmp, "does-not-exist", "anywhere")
        with self.assertRaises(WorkspacePathError) as ctx:
            validate_workspace_path(bogus)
        self.assertIn("does not exist", str(ctx.exception))

    def test_rejects_file_not_directory(self):
        f = os.path.join(self.tmp, "regular-file")
        with open(f, "w") as h:
            h.write("not a directory")
        with self.assertRaises(WorkspacePathError) as ctx:
            validate_workspace_path(f)
        self.assertIn("not a directory", str(ctx.exception))

    def test_rejects_directory_without_cursor_markers(self):
        # Existing directory but no state.vscdb anywhere — common case for
        # a user pointing at /tmp, /etc, /, ~/.ssh, etc.
        plain = os.path.join(self.tmp, "plain-dir")
        os.makedirs(os.path.join(plain, "subdir"))
        with self.assertRaises(WorkspacePathError) as ctx:
            validate_workspace_path(plain)
        self.assertIn("Cursor workspaceStorage", str(ctx.exception))

    # ─── Path-traversal class ──────────────────────────────────────

    def test_traversal_into_non_workspace_is_rejected(self):
        # /tmp/<x>/real-storage/../../  → /tmp/  → no Cursor markers → reject
        storage = _make_cursor_workspace_dir(self.tmp)
        escape = os.path.join(storage, "..", "..")
        with self.assertRaises(WorkspacePathError):
            validate_workspace_path(escape)

    # ─── Symlink-escape class ──────────────────────────────────────

    @unittest.skipIf(sys.platform == "win32", "POSIX symlinks only")
    def test_symlink_to_non_workspace_is_rejected(self):
        # A symlink that points to / (no Cursor markers) is rejected because
        # realpath() resolves to the real target before the marker check.
        link = os.path.join(self.tmp, "evil-link")
        os.symlink("/", link)
        with self.assertRaises(WorkspacePathError) as ctx:
            validate_workspace_path(link)
        self.assertIn("Cursor workspaceStorage", str(ctx.exception))

    @unittest.skipIf(sys.platform == "win32", "POSIX symlinks only")
    def test_symlink_to_real_workspace_is_canonicalised_and_accepted(self):
        # Symlink → real Cursor storage. Accepted, but the canonical path
        # returned is the realpath (the storage dir), NOT the symlink path.
        storage = _make_cursor_workspace_dir(self.tmp)
        link = os.path.join(self.tmp, "good-link")
        os.symlink(storage, link)
        result = validate_workspace_path(link)
        self.assertEqual(result, os.path.realpath(storage))
        self.assertNotEqual(result, link)


if __name__ == "__main__":
    unittest.main()
