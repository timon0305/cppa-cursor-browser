"""
API routes for configuration — mirrors:
  src/app/api/detect-environment/route.ts  GET /api/detect-environment
  src/app/api/validate-path/route.ts       POST /api/validate-path
  src/app/api/set-workspace/route.ts       POST /api/set-workspace
  src/app/api/get-username/route.ts        GET /api/get-username
"""

import os
import subprocess
import sys

from flask import Blueprint, jsonify, request

from utils.path_helpers import expand_tilde_path
from utils.workspace_path import set_workspace_path_override

bp = Blueprint("config_api", __name__)


@bp.route("/api/detect-environment")
def detect_environment():
    try:
        is_wsl = False
        is_remote = bool(
            os.environ.get("SSH_CONNECTION")
            or os.environ.get("SSH_CLIENT")
            or os.environ.get("SSH_TTY")
        )

        if sys.platform != "win32":
            try:
                release = subprocess.check_output(
                    ["uname", "-r"], text=True, stderr=subprocess.DEVNULL
                ).lower()
                is_wsl = "microsoft" in release or "wsl" in release
            except Exception:
                pass

        return jsonify({
            "os": sys.platform,
            "isWSL": is_wsl,
            "isRemote": is_remote,
        })

    except Exception as e:
        print(f"Failed to detect environment: {e}")
        return jsonify({"os": "unknown", "isWSL": False, "isRemote": False})


@bp.route("/api/validate-path", methods=["POST"])
def validate_path():
    try:
        body = request.get_json(silent=True) or {}
        workspace_path = body.get("path", "")
        expanded = expand_tilde_path(workspace_path)

        if not os.path.isdir(expanded):
            return jsonify({"valid": False, "error": "Path does not exist"})

        workspace_count = 0
        for name in os.listdir(expanded):
            full = os.path.join(expanded, name)
            if os.path.isdir(full):
                db = os.path.join(full, "state.vscdb")
                if os.path.isfile(db):
                    workspace_count += 1

        return jsonify({"valid": workspace_count > 0, "workspaceCount": workspace_count})

    except Exception as e:
        print(f"Validation error: {e}")
        return jsonify({"valid": False, "error": "Failed to validate path"}), 500


@bp.route("/api/set-workspace", methods=["POST"])
def set_workspace():
    try:
        body = request.get_json(silent=True) or {}
        path = body.get("path", "")
        expanded = expand_tilde_path(path)
        set_workspace_path_override(expanded)
        return jsonify({"success": True})
    except Exception:
        return jsonify({"error": "Failed to set workspace path"}), 500


@bp.route("/api/get-username")
def get_username():
    try:
        username = "YOUR_USERNAME"

        if sys.platform == "win32":
            username = os.environ.get("USERNAME") or os.getlogin()
        else:
            try:
                output = subprocess.check_output(
                    ["cmd.exe", "/c", "echo", "%USERNAME%"],
                    text=True,
                    stderr=subprocess.DEVNULL,
                )
                username = output.strip()
            except Exception:
                import getpass
                username = getpass.getuser()

        return jsonify({"username": username})

    except Exception as e:
        print(f"Failed to get username: {e}")
        return jsonify({"username": "YOUR_USERNAME"})
