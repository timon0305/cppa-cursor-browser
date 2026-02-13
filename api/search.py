"""
API route for search — mirrors src/app/api/search/route.ts
GET /api/search?q=...&type=all|chat|composer
"""

import json
import os
import re
import sqlite3
from datetime import datetime

from flask import Blueprint, jsonify, request

from utils.workspace_path import resolve_workspace_path
from utils.path_helpers import normalize_file_path, get_workspace_folder_paths, to_epoch_ms
from utils.text_extract import extract_text_from_bubble

bp = Blueprint("search", __name__)


@bp.route("/api/search")
def search():
    try:
        query = request.args.get("q", "").strip()
        search_type = request.args.get("type", "all")

        if not query:
            return jsonify({"error": "No search query provided"}), 400

        workspace_path = resolve_workspace_path()
        results = []
        query_lower = query.lower()

        global_db_path = os.path.normpath(os.path.join(workspace_path, "..", "globalStorage", "state.vscdb"))

        # ---------------------------------------------------------------
        # Search global cursorDiskKV (new Cursor format — primary source)
        # ---------------------------------------------------------------
        if os.path.isfile(global_db_path):
            try:
                conn = sqlite3.connect(f"file:{global_db_path}?mode=ro", uri=True)
                conn.row_factory = sqlite3.Row

                # Build workspace name map for display
                workspace_entries = []
                ws_id_to_name = {}
                try:
                    for name in os.listdir(workspace_path):
                        full = os.path.join(workspace_path, name)
                        wj = os.path.join(full, "workspace.json")
                        if os.path.isdir(full) and os.path.isfile(wj):
                            workspace_entries.append({"name": name, "workspaceJsonPath": wj})
                            try:
                                with open(wj, "r", encoding="utf-8") as f:
                                    wd = json.load(f)
                                first_folder = wd.get("folder") or (wd.get("folders", [{}])[0] or {}).get("path")
                                if first_folder:
                                    parts = first_folder.replace("\\", "/").split("/")
                                    fn = parts[-1] if parts else None
                                    if fn:
                                        ws_id_to_name[name] = fn
                            except Exception:
                                pass
                except Exception:
                    pass

                # Build composer → workspace mapping
                composer_id_to_ws = {}
                for entry in workspace_entries:
                    db_path = os.path.join(workspace_path, entry["name"], "state.vscdb")
                    if not os.path.isfile(db_path):
                        continue
                    try:
                        wconn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
                        row = wconn.execute(
                            "SELECT value FROM ItemTable WHERE [key] = 'composer.composerData'"
                        ).fetchone()
                        if row and row[0]:
                            data = json.loads(row[0])
                            all_composers = data.get("allComposers")
                            if isinstance(all_composers, list):
                                for c in all_composers:
                                    cid = c.get("composerId") if isinstance(c, dict) else None
                                    if cid:
                                        composer_id_to_ws[cid] = entry["name"]
                        wconn.close()
                    except Exception:
                        pass

                # Load bubble text for searching
                bubble_map = {}
                for row in conn.execute("SELECT key, value FROM cursorDiskKV WHERE key LIKE 'bubbleId:%'"):
                    parts = row["key"].split(":")
                    if len(parts) >= 3:
                        bid = parts[2]
                        try:
                            b = json.loads(row["value"])
                            if isinstance(b, dict):
                                text = extract_text_from_bubble(b)
                                bubble_map[bid] = {"text": text, "raw": b}
                        except Exception:
                            pass

                # Search through composerData
                composer_rows = conn.execute(
                    "SELECT key, value FROM cursorDiskKV WHERE key LIKE 'composerData:%' AND LENGTH(value) > 10"
                ).fetchall()

                for row in composer_rows:
                    composer_id = row["key"].split(":")[1]
                    try:
                        cd = json.loads(row["value"])
                        headers = cd.get("fullConversationHeadersOnly") or []
                        if not headers:
                            continue

                        # Check if any bubble text matches
                        has_match = False
                        matching_text = ""
                        title = cd.get("name") or ""

                        # Check title
                        if title and query_lower in title.lower():
                            has_match = True
                            matching_text = title

                        # Check bubble texts
                        if not has_match:
                            for header in headers:
                                bid = header.get("bubbleId")
                                bubble_entry = bubble_map.get(bid)
                                if bubble_entry:
                                    text = bubble_entry["text"]
                                    if text and query_lower in text.lower():
                                        has_match = True
                                        # Extract a snippet around the match
                                        idx = text.lower().find(query_lower)
                                        start = max(0, idx - 80)
                                        end = min(len(text), idx + len(query) + 120)
                                        matching_text = ("..." if start > 0 else "") + text[start:end] + ("..." if end < len(text) else "")
                                        break

                        if has_match:
                            ws_id = composer_id_to_ws.get(composer_id, "global")
                            ws_name = ws_id_to_name.get(ws_id)
                            if not title:
                                # Derive title from first bubble
                                for header in headers:
                                    be = bubble_map.get(header.get("bubbleId"))
                                    if be and be["text"]:
                                        first_lines = [l for l in be["text"].split("\n") if l.strip()]
                                        if first_lines:
                                            title = first_lines[0][:100]
                                        break
                                if not title:
                                    title = f"Conversation {composer_id[:8]}"

                            results.append({
                                "workspaceId": ws_id,
                                "workspaceFolder": ws_name,
                                "chatId": composer_id,
                                "chatTitle": title,
                                "timestamp": to_epoch_ms(cd.get("lastUpdatedAt")) or to_epoch_ms(cd.get("createdAt")) or int(datetime.now().timestamp() * 1000),
                                "matchingText": matching_text,
                                "type": "composer",
                            })
                    except Exception:
                        pass

                conn.close()
            except Exception as e:
                print(f"Error searching global storage: {e}")

        # ---------------------------------------------------------------
        # Search per-workspace ItemTable (legacy format — fallback)
        # ---------------------------------------------------------------
        try:
            for name in os.listdir(workspace_path):
                full = os.path.join(workspace_path, name)
                if not os.path.isdir(full):
                    continue
                db_path = os.path.join(full, "state.vscdb")
                wj_path = os.path.join(full, "workspace.json")
                if not os.path.isfile(db_path):
                    continue

                workspace_folder = None
                try:
                    with open(wj_path, "r", encoding="utf-8") as f:
                        wd = json.load(f)
                    workspace_folder = wd.get("folder")
                except Exception:
                    pass

                try:
                    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)

                    # Search chat logs
                    if search_type in ("all", "chat"):
                        chat_row = conn.execute(
                            "SELECT value FROM ItemTable WHERE [key] = 'workbench.panel.aichat.view.aichat.chatdata'"
                        ).fetchone()
                        if chat_row and chat_row[0]:
                            data = json.loads(chat_row[0])
                            for tab in (data.get("tabs") or []):
                                has_match = False
                                matching_text = ""

                                ct = tab.get("chatTitle") or ""
                                if ct.lower().find(query_lower) != -1:
                                    has_match = True
                                    matching_text = ct

                                for bubble in (tab.get("bubbles") or []):
                                    text = bubble.get("text") or ""
                                    if text.lower().find(query_lower) != -1:
                                        has_match = True
                                        idx = text.lower().find(query_lower)
                                        start = max(0, idx - 80)
                                        end = min(len(text), idx + len(query) + 120)
                                        matching_text = ("..." if start > 0 else "") + text[start:end] + ("..." if end < len(text) else "")
                                        break

                                if has_match:
                                    results.append({
                                        "workspaceId": name,
                                        "workspaceFolder": workspace_folder,
                                        "chatId": tab.get("tabId"),
                                        "chatTitle": ct or f"Chat {(tab.get('tabId') or '')[:8]}",
                                        "timestamp": tab.get("lastSendTime") or datetime.now().isoformat(),
                                        "matchingText": matching_text,
                                        "type": "chat",
                                    })

                    conn.close()
                except Exception:
                    pass
        except Exception:
            pass

        # Sort by timestamp descending
        def _ts(r):
            t = r.get("timestamp", 0)
            if isinstance(t, str):
                try:
                    return datetime.fromisoformat(t.replace("Z", "+00:00")).timestamp()
                except Exception:
                    return 0
            return t
        results.sort(key=_ts, reverse=True)

        return jsonify({"results": results})

    except Exception as e:
        print(f"Search failed: {e}")
        return jsonify({"error": "Search failed", "results": []}), 500
