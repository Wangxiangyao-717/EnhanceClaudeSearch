import json
import os
import platform
import re
import shutil
import subprocess
import sys
import unicodedata
from datetime import datetime

from prompt_toolkit import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.output import create_output as _create_output
from prompt_toolkit.output.win32 import NoConsoleScreenBufferError
from prompt_toolkit.input import create_input as _create_input
from prompt_toolkit.styles import Style


# ---------------------------------------------------------------------------
# Config persistence
# ---------------------------------------------------------------------------

CONFIG_PATH = os.path.expanduser("~/.enhance_claude_search.json")

DEFAULT_CONFIG = {
    "cmd_prefix": "claude -r",
    "cmd_suffix": "",
}


def load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                return {**DEFAULT_CONFIG, **cfg}
        except Exception:
            pass
    return dict(DEFAULT_CONFIG)


def save_config(config):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Clipboard
# ---------------------------------------------------------------------------

def copy_to_clipboard(text):
    system = platform.system()
    try:
        if system == "Windows":
            subprocess.run("clip", input=text.encode("utf-16-le"), check=False)
        elif system == "Darwin":
            subprocess.run("pbcopy", input=text.encode(), check=False)
        else:
            for cmd in ["wl-copy", "xclip -selection clipboard"]:
                try:
                    subprocess.run(cmd.split(), input=text.encode(), check=True)
                    return
                except Exception:
                    continue
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Session discovery
# ---------------------------------------------------------------------------

def display_width(text):
    """Terminal display width — CJK characters count as 2, others as 1."""
    w = 0
    for ch in text:
        w += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return w


def wrap_display(text, width):
    """Wrap text at given display width, correctly handling CJK characters."""
    lines = []
    current = ""
    current_w = 0
    for ch in text:
        ch_w = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        if ch == "\n":
            lines.append(current)
            current = ""
            current_w = 0
        elif current_w + ch_w > width:
            lines.append(current)
            current = ch
            current_w = ch_w
        else:
            current += ch
            current_w += ch_w
    if current:
        lines.append(current)
    return lines if lines else [""]


def project_session_dir(project_path=None):
    """Map a filesystem path to the Claude Code session directory name."""
    if project_path is None:
        project_path = os.getcwd()
    abs_path = os.path.abspath(project_path)
    dir_name = abs_path.replace(":", "-").replace("\\", "-").replace("/", "-").replace("_", "-")
    sessions_root = os.path.expanduser("~/.claude/projects")
    session_dir = os.path.join(sessions_root, dir_name)
    if os.path.isdir(session_dir):
        return session_dir, abs_path
    # Fallback: try the immediate parent directory (one level up)
    parent_abs = os.path.dirname(abs_path)
    if parent_abs and parent_abs != abs_path:
        parent_name = parent_abs.replace(":", "-").replace("\\", "-").replace("/", "-").replace("_", "-")
        parent_session = os.path.join(sessions_root, parent_name)
        if os.path.isdir(parent_session):
            return parent_session, abs_path
    return None, abs_path


# ---------------------------------------------------------------------------
# Session indexing
# ---------------------------------------------------------------------------

def extract_session_info(jsonl_path):
    """Extract first user prompt, all searchable text, and mtime."""
    info = {
        "uuid": os.path.basename(jsonl_path).replace(".jsonl", ""),
        "first_prompt": "",
        "search_text": "",
        "mtime": os.path.getmtime(jsonl_path),
        "date_str": "",
    }
    try:
        info["date_str"] = datetime.fromtimestamp(info["mtime"]).strftime("%m-%d %H:%M")
    except Exception:
        info["date_str"] = "??-?? ??:??"

    try:
        with open(jsonl_path, "r", encoding="utf-8") as f:
            all_texts = []
            first_found = False
            for line in f:
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if d.get("type") != "user":
                    continue
                msg = d.get("message", {})
                content = msg.get("content", "")
                if isinstance(content, list):
                    texts = [
                        b.get("text", "")
                        for b in content
                        if isinstance(b, dict) and b.get("type") == "text"
                    ]
                    content = " ".join(texts)
                clean = re.sub(r"<[^>]+>", " ", content)
                clean = re.sub(r"\s+", " ", clean).strip()
                if clean:
                    all_texts.append(clean)
                    if not first_found:
                        info["first_prompt"] = clean
                        first_found = True
        info["search_text"] = " ".join(all_texts)
    except Exception:
        pass

    if not info["first_prompt"] and info["search_text"]:
        info["first_prompt"] = info["search_text"][:120]

    return info


def build_index(session_dir):
    """Scan all session JSONL files and build search index."""
    sessions = []
    if not session_dir or not os.path.isdir(session_dir):
        return sessions
    for fname in os.listdir(session_dir):
        if not fname.endswith(".jsonl"):
            continue
        info = extract_session_info(os.path.join(session_dir, fname))
        if info["search_text"] or info["first_prompt"]:
            sessions.append(info)
    sessions.sort(key=lambda s: s["mtime"], reverse=True)
    return sessions


def load_session_messages(session_dir, uuid):
    """Load all user messages from a session JSONL file, in order."""
    jsonl_path = os.path.join(session_dir, uuid + ".jsonl")
    messages = []
    try:
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if d.get("type") != "user":
                    continue
                msg = d.get("message", {})
                content = msg.get("content", "")
                if isinstance(content, list):
                    texts = [
                        b.get("text", "")
                        for b in content
                        if isinstance(b, dict) and b.get("type") == "text"
                    ]
                    content = " ".join(texts)
                clean = re.sub(r"<[^>]+>", " ", content)
                clean = re.sub(r"\s+", " ", clean).strip()
                if clean:
                    messages.append(clean)
    except Exception:
        pass
    return messages


def load_session_recap(session_dir, uuid):
    """Load the most recent recap (away_summary) from a session JSONL file."""
    jsonl_path = os.path.join(session_dir, uuid + ".jsonl")
    try:
        with open(jsonl_path, "r", encoding="utf-8") as f:
            recap = None
            for line in f:
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if d.get("type") == "system" and d.get("subtype") == "away_summary":
                    recap = d.get("content", "")
            return recap
    except Exception:
        return None


def find_match_snippet(search_text, query, context_chars=10):
    """Extract text around the first matching term for context display."""
    if not query or not query.strip():
        return ""
    terms = query.strip().lower().split()
    text_lower = search_text.lower()

    first_pos = len(text_lower)
    first_len = 0
    for term in terms:
        pos = text_lower.find(term)
        if pos != -1 and pos < first_pos:
            first_pos = pos
            first_len = len(term)

    if first_pos == len(text_lower):
        return ""

    start = max(0, first_pos - context_chars)
    end = min(len(search_text), first_pos + first_len + context_chars)
    snippet = search_text[start:end].replace("\n", " ")

    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(search_text) else ""

    return f"{prefix}{snippet}{suffix}"


def filter_sessions(sessions, query):
    """Filter sessions by query against search_text (AND match)."""
    if not query or not query.strip():
        return list(sessions)
    terms = query.strip().lower().split()
    results = []
    for s in sessions:
        text = (s["first_prompt"] + " " + s["search_text"]).lower()
        if all(t in text for t in terms):
            results.append(s)
    return results


def filter_sessions_with_snippets(sessions, query):
    """Filter sessions and annotate each with a match snippet."""
    filtered = filter_sessions(sessions, query)
    for s in filtered:
        s["match_snippet"] = find_match_snippet(s["search_text"], query)
    return filtered


# ---------------------------------------------------------------------------
