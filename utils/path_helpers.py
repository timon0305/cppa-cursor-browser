"""Path utility functions mirroring src/utils/path.ts"""

import os
import sys
from datetime import datetime


def expand_tilde_path(input_path: str) -> str:
    """Expand ~ in paths and handle macOS Library paths."""
    home = os.path.expanduser("~")

    # Handle paths that start with ~/
    if input_path.startswith("~/"):
        return os.path.join(home, input_path[2:])

    # If the path already contains the home directory, return as is
    if input_path.startswith(home):
        return input_path

    # Handle macOS Library paths that should start with home dir
    if "Library/Application Support" in input_path and not input_path.startswith(home):
        return os.path.join(home, input_path)

    return input_path


def normalize_file_path(file_path: str) -> str:
    """Normalize a file path: strip file:// protocol, URL-decode, fix slashes."""
    import re
    from urllib.parse import unquote

    normalized = file_path
    # Remove file:// protocol
    normalized = re.sub(r"^file:///", "", normalized)
    normalized = re.sub(r"^file://", "", normalized)

    # URL-decode the path
    try:
        normalized = unquote(normalized)
    except Exception:
        pass

    # Platform-specific normalization
    if sys.platform == "win32":
        normalized = normalized.replace("/", "\\")
        # Remove leading backslash before drive letter
        normalized = re.sub(r"^\\([a-zA-Z]:)", r"\1", normalized)
        normalized = normalized.lower()

    return normalized


def to_epoch_ms(value) -> int:
    """Convert a timestamp value to epoch milliseconds.

    Handles:
      - int/float already in ms (> 1e12) or seconds (< 1e12)
      - ISO 8601 strings like '2026-02-03T20:39:54.017Z'
      - None / unrecognised → 0
    """
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        if value > 1e12:
            return int(value)           # already ms
        if value > 0:
            return int(value * 1000)    # seconds → ms
        return 0
    if isinstance(value, str):
        try:
            # ISO 8601 with optional fractional seconds
            cleaned = value.rstrip("Z") + "+00:00" if value.endswith("Z") else value
            dt = datetime.fromisoformat(cleaned)
            return int(dt.timestamp() * 1000)
        except Exception:
            pass
        # Maybe it's a numeric string?
        try:
            return to_epoch_ms(float(value))
        except Exception:
            pass
    return 0


def get_workspace_folder_paths(workspace_data: dict) -> list:
    """Extract folder paths from workspace.json data."""
    paths = []
    if workspace_data.get("folder"):
        paths.append(workspace_data["folder"])
    folders = workspace_data.get("folders")
    if isinstance(folders, list):
        for f in folders:
            if isinstance(f, dict) and f.get("path"):
                paths.append(f["path"])
    return paths
