#!/usr/bin/env python
"""Interactive session search for Claude Code.

Scans Claude Code session JSONL files to provide full-text search across
conversation history, replacing the default title-only search in `claude -r`.

Three input fields:
  1. Cmd   - command prefix (saved across sessions)
  2. Arg   - additional args (saved across sessions)
  3. Search - full-text filter

Keys:
  Tab/Shift+Tab  switch focus
  Up/Down        navigate results
  Enter          run: {cmd} {uuid} {arg}
  Space          copy uuid to clipboard (when search is focused)
  Esc            quit

Usage:
    python session_search.py              # Interactive TUI
    python session_search.py keyword      # TUI with pre-filled search
    python session_search.py --list kw    # Non-interactive list mode
"""

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
# TUI
# ---------------------------------------------------------------------------

STYLE = Style.from_dict({
    "input-row": "bg:#1a1a2e fg:#e0e0e0",
    "input-label": "fg:#00d4aa bold",
    "input-label-focused": "fg:#00ffcc bold underline",
    "input-text": "fg:#e0e0e0",
    "input-text-focused": "bg:#2a2a4e fg:#ffffff",
    "result-item": "fg:#c0c0c0",
    "result-selected": "bg:#00d4aa fg:#0a0a0a bold",
    "status-bar": "bg:#0a0a1a fg:#888888",
    "status-key": "fg:#00d4aa bold",
    "no-results": "fg:#ff6b6b",
    "header": "fg:#666666",
})


class SessionPicker:
    """Interactive full-screen session search TUI with three input fields."""

    def __init__(self, sessions, config, session_dir, initial_query=""):
        self.sessions = sessions
        self.session_dir = session_dir
        self.cmd_prefix = config.get("cmd_prefix", "claude -r")
        self.cmd_suffix = config.get("cmd_suffix", "")
        self.query = initial_query
        self.selected_idx = 0
        self.filtered = []
        self.focus_index = 2  # 0=cmd, 1=suffix, 2=search
        self.detail_mode = False
        self.detail_messages = []
        self.detail_recap = None
        self.detail_idx = 0
        self.detail_uuid = None

    @property
    def config(self):
        return {
            "cmd_prefix": self.cmd_prefix,
            "cmd_suffix": self.cmd_suffix,
        }

    def run(self):
        kb = KeyBindings()

        # --- Navigation ---

        @kb.add("up")
        def _(event):
            if self.detail_mode:
                self.detail_idx = max(0, self.detail_idx - 1)
            else:
                self.selected_idx = max(0, self.selected_idx - 1)
            self._refresh(event)

        @kb.add("down")
        def _(event):
            if self.detail_mode:
                if self.detail_messages:
                    self.detail_idx = min(len(self.detail_messages) - 1, self.detail_idx + 1)
            else:
                if self.filtered:
                    self.selected_idx = min(len(self.filtered) - 1, self.selected_idx + 1)
            self._refresh(event)

        @kb.add("c-n")
        def _(event):
            if self.filtered:
                self.selected_idx = min(len(self.filtered) - 1, self.selected_idx + 10)
            self._refresh(event)

        @kb.add("c-p")
        def _(event):
            self.selected_idx = max(0, self.selected_idx - 10)
            self._refresh(event)

        # --- Focus switching ---

        @kb.add("tab")
        def _(event):
            self.focus_index = (self.focus_index + 1) % 3
            self._refresh(event)

        @kb.add("s-tab")
        def _(event):
            self.focus_index = (self.focus_index - 1) % 3
            self._refresh(event)

        # --- Exit ---

        @kb.add("escape")
        @kb.add("c-c")
        def _(event):
            if self.detail_mode:
                self.detail_mode = False
                self._refresh(event)
            else:
                event.app.exit(result=None)

        # --- Detail view ---

        @kb.add("right")
        def _(event):
            if not self.detail_mode and self.filtered and self.selected_idx < len(self.filtered):
                uuid = self.filtered[self.selected_idx]["uuid"]
                self.detail_messages = load_session_messages(self.session_dir, uuid)
                self.detail_recap = load_session_recap(self.session_dir, uuid)
                self.detail_idx = 0
                self.detail_uuid = uuid
                self.detail_mode = True
                self._refresh(event)

        @kb.add("left")
        def _(event):
            if self.detail_mode:
                self.detail_mode = False
                self._refresh(event)

        # --- Enter: execute command ---

        @kb.add("enter")
        def _(event):
            if self.filtered and self.selected_idx < len(self.filtered):
                uuid = self.filtered[self.selected_idx]["uuid"]
                event.app.exit(result=("run", uuid))

        # --- Space: copy uuid or type space ---

        @kb.add("space")
        def _(event):
            if self.focus_index == 2 and self.filtered and self.selected_idx < len(self.filtered):
                uuid = self.filtered[self.selected_idx]["uuid"]
                copy_to_clipboard(uuid)
            elif self.focus_index == 0:
                self.cmd_prefix += " "
            elif self.focus_index == 1:
                self.cmd_suffix += " "
            self._refresh(event)

        # --- Text input ---

        @kb.add("<any>")
        def _(event):
            if not event.data or len(event.data) != 1:
                return
            ch = event.data
            if ch == " " or not ch.isprintable():
                return
            if self.focus_index == 0:
                self.cmd_prefix += ch
            elif self.focus_index == 1:
                self.cmd_suffix += ch
            else:
                self.query += ch
                self.selected_idx = 0
            self._refresh(event)

        # --- Deletion ---

        @kb.add("backspace")
        @kb.add("c-h")
        def _(event):
            if self.focus_index == 0:
                self.cmd_prefix = self.cmd_prefix[:-1]
            elif self.focus_index == 1:
                self.cmd_suffix = self.cmd_suffix[:-1]
            else:
                self.query = self.query[:-1]
                self.selected_idx = 0
            self._refresh(event)

        @kb.add("c-u")
        def _(event):
            if self.focus_index == 0:
                self.cmd_prefix = ""
            elif self.focus_index == 1:
                self.cmd_suffix = ""
            else:
                self.query = ""
                self.selected_idx = 0
            self._refresh(event)

        @kb.add("c-w")
        def _(event):
            if self.focus_index == 2:
                self.query = re.sub(r"\S+\s*$", "", self.query)
                self.selected_idx = 0
            elif self.focus_index == 0:
                self.cmd_prefix = re.sub(r"\S+\s*$", "", self.cmd_prefix)
            elif self.focus_index == 1:
                self.cmd_suffix = re.sub(r"\S+\s*$", "", self.cmd_suffix)
            self._refresh(event)

        loading = Window(
            content=FormattedTextControl([
                ("class:status-bar", "  Loading sessions...")
            ]),
            height=1,
        )

        # On Windows, try the native console output/input; fall back to VT100
        # if running inside a terminal emulator (WezTerm, Windows Terminal,
        # WSL, Cygwin, etc.).
        try:
            output = _create_output()
        except NoConsoleScreenBufferError:
            import shutil
            from collections import namedtuple

            from prompt_toolkit.output.vt100 import Vt100_Output

            _Size = namedtuple("Size", "rows columns")

            def _get_terminal_size():
                try:
                    s = shutil.get_terminal_size()
                    return _Size(rows=s.lines, columns=s.columns)
                except Exception:
                    return _Size(rows=24, columns=80)

            output = Vt100_Output(
                sys.stdout,
                get_size=_get_terminal_size,
                term="xterm-256color",
            )

        try:
            _input = _create_input()
        except (NoConsoleScreenBufferError, Exception):
            from prompt_toolkit.input.vt100 import Vt100Input
            _input = Vt100Input(sys.stdin)

        self.app = Application(
            layout=Layout(HSplit([loading])),
            key_bindings=kb,
            output=output,
            input=_input,
            style=STYLE,
            full_screen=True,
        )
        self._refresh(None)
        return self.app.run()

    def _make_input_row(self, label, value, focus_idx):
        """Build a Window for one input row."""
        focused = self.focus_index == focus_idx
        label_class = "input-label-focused" if focused else "input-label"
        text_class = "input-text-focused" if focused else "input-text"
        cursor = " " if focused else ""
        return Window(
            content=FormattedTextControl([
                ("class:" + label_class, f"  {label} "),
                ("class:" + text_class, value + cursor),
            ]),
            height=1,
            style="class:input-row",
        )

    def _refresh(self, event):
        if self.detail_mode:
            self._refresh_detail()
            return

        self.filtered = filter_sessions_with_snippets(self.sessions, self.query)
        if self.selected_idx < 0:
            self.selected_idx = 0
        if self.filtered and self.selected_idx >= len(self.filtered):
            self.selected_idx = len(self.filtered) - 1
        if not self.filtered:
            self.selected_idx = 0

        rows = []

        # Three input rows
        rows.append(self._make_input_row("Cmd:   ", self.cmd_prefix, 0))
        rows.append(self._make_input_row("Arg:   ", self.cmd_suffix, 1))
        rows.append(self._make_input_row("Search:", self.query, 2))

        # Header
        rows.append(Window(
            content=FormattedTextControl([
                ("class:header", "  DATE       UUID       TOPIC / MATCH"),
            ]),
            height=1,
        ))

        # Results
        lines = []
        if not self.filtered:
            if self.query.strip():
                lines.append(("class:no-results", f"  No sessions matching '{self.query.strip()}'\n"))
            else:
                lines.append(("class:no-results", "  No sessions found\n"))
        else:
            for i, s in enumerate(self.filtered):
                is_selected = i == self.selected_idx
                prefix = ">" if is_selected else " "
                line_class = "class:result-selected" if is_selected else "class:result-item"
                prompt_text = s["first_prompt"][:60] or "(empty)"
                snippet = s.get("match_snippet", "")
                if snippet:
                    prompt_text = f"{prompt_text}  {snippet}"
                line = f"{prefix} {s['date_str']}  {s['uuid'][:8]}  {prompt_text}\n"
                lines.append((line_class, line))

        # Virtual scrolling: only render the visible window of results
        term_height = shutil.get_terminal_size().lines
        fixed_rows = 5  # 3 inputs + 1 header + 1 status
        visible_rows = max(1, term_height - fixed_rows)
        result_count = len(self.filtered) if self.filtered else 0

        if result_count > visible_rows:
            start = max(0, self.selected_idx - visible_rows // 2)
            start = min(start, result_count - visible_rows)
            lines = lines[start:start + visible_rows]

        rows.append(Window(
            content=FormattedTextControl(text=lines, focusable=False),
            wrap_lines=False,
        ))

        # Status bar
        match_count = len(self.filtered) if self.filtered else 0
        total = len(self.sessions)
        cmd_preview = ""
        if self.filtered and self.selected_idx < len(self.filtered):
            uuid_short = self.filtered[self.selected_idx]["uuid"][:8]
            parts = [p for p in [self.cmd_prefix, uuid_short, self.cmd_suffix] if p]
            cmd_preview = f"Run: {' '.join(parts)} | "

        focus_labels = ["Cmd", "Arg", "Search"]
        focus_name = focus_labels[self.focus_index]
        status_text = (
            f"  {match_count}/{total} | {cmd_preview}"
            f"Tab 切换输入框 [{focus_name}]  Enter 执行  Space 复制UUID  Esc 退出"
        )
        rows.append(Window(
            content=FormattedTextControl([
                ("class:status-bar", status_text),
            ]),
            height=1,
        ))

        self.app.layout = Layout(HSplit(rows))

    def _refresh_detail(self):
        """Render the detail view showing recap (fixed) and user messages."""
        info = next((s for s in self.sessions if s["uuid"] == self.detail_uuid), None)
        date_str = info["date_str"] if info else "??-?? ??:??"
        uuid_short = (self.detail_uuid or "")[:8]

        term_height = shutil.get_terminal_size().lines
        term_width = shutil.get_terminal_size().columns
        max_msg_width = max(20, term_width - 6)

        msg_count = len(self.detail_messages)
        if self.detail_idx < 0:
            self.detail_idx = 0
        if msg_count and self.detail_idx >= msg_count:
            self.detail_idx = msg_count - 1
        if not msg_count:
            self.detail_idx = 0

        rows = []

        # --- Recap section (fixed at top) ---
        recap_lines = 0
        recap_text = self.detail_recap or ""
        if recap_text.strip():
            # Wrap recap text to terminal width, show up to 5 lines
            max_recap_width = max(20, term_width - 4)
            wrapped = wrap_display(recap_text.strip(), width=max_recap_width)
            recap_display = wrapped[:5]
            if len(wrapped) > 5:
                recap_display[-1] = recap_display[-1][:max_recap_width - 3] + "..."

            for i, line in enumerate(recap_display):
                prefix = "  Recap: " if i == 0 else "         "
                rows.append(Window(
                    content=FormattedTextControl([
                        ("class:input-label", f"{prefix}{line}"),
                    ]),
                    height=1,
                    style="class:input-row",
                ))
            recap_lines = len(recap_display)

        # --- Session info bar ---
        top_text = f"  Session: {uuid_short}    {date_str}    {msg_count} messages"
        rows.append(Window(
            content=FormattedTextControl([
                ("class:input-label", top_text),
            ]),
            height=1,
            style="class:input-row",
        ))

        # --- Separator ---
        rows.append(Window(
            content=FormattedTextControl([
                ("class:header", f"  {'─' * (term_width - 4)}"),
            ]),
            height=1,
        ))

        # --- Message list with scroll ---
        fixed_rows = 2 + recap_lines  # session bar(1) + separator(1) + status(1) + recap
        visible_rows = max(1, term_height - fixed_rows - 1)  # -1 for status bar

        start = 0
        if msg_count > visible_rows:
            start = max(0, self.detail_idx - visible_rows // 2)
            start = min(start, msg_count - visible_rows)

        lines = []
        if not self.detail_messages:
            lines.append(("class:no-results", "  No user messages found\n"))
        else:
            visible = self.detail_messages[start:start + visible_rows]
            for i, msg in enumerate(visible):
                actual_idx = start + i
                is_selected = actual_idx == self.detail_idx
                prefix = ">" if is_selected else " "
                line_class = "class:result-selected" if is_selected else "class:result-item"
                truncated = msg[:max_msg_width]
                line = f"{prefix}{actual_idx + 1:>3}. {truncated}\n"
                lines.append((line_class, line))

        rows.append(Window(
            content=FormattedTextControl(text=lines, focusable=False),
            wrap_lines=False,
        ))

        # --- Status bar ---
        status_text = (
            f"  {self.detail_idx + 1}/{msg_count}"
            f"    ← 返回主界面    ↑↓ 选择    Esc 返回"
        )
        rows.append(Window(
            content=FormattedTextControl([
                ("class:status-bar", status_text),
            ]),
            height=1,
        ))

        self.app.layout = Layout(HSplit(rows))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    list_mode = "--list" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--list"]

    session_dir, project_path = project_session_dir()

    if not session_dir:
        print(f"No Claude Code session directory found for: {project_path}")
        sys.exit(1)

    sessions = build_index(session_dir)
    if not sessions:
        print(f"No sessions found in: {session_dir}")
        sys.exit(1)

    config = load_config()

    query_override = " ".join(args) if args else None

    if list_mode:
        query = query_override or ""
        filtered = filter_sessions(sessions, query)
        if not filtered:
            print(f"No sessions matching: {query}")
            sys.exit(0)
        print(f"\n{'DATE':<12} {'UUID':<10} TOPIC")
        print("-" * 80)
        for s in filtered[:20]:
            print(f"{s['date_str']:<12} {s['uuid'][:8]:<10} {s['first_prompt'][:100]}")
        print(f"\n{len(filtered)} match(es). Use `claude -r <uuid>` to resume.\n")
        sys.exit(0)

    # Interactive TUI
    picker = SessionPicker(sessions, config, session_dir, query_override or "")
    result = picker.run()

    # Always save config on exit
    save_config(picker.config)

    print("\033[2J\033[H", end="")

    if result is None:
        print("Cancelled.")
    elif result[0] == "run":
        uuid = result[1]
        info = next((s for s in sessions if s["uuid"] == uuid), None)
        parts = [p for p in [picker.cmd_prefix, uuid, picker.cmd_suffix] if p]
        cmd = " ".join(parts)
        print(f"Running: {cmd}")
        if info:
            print(f"  {info['date_str']}  {info['first_prompt'][:120]}")
        os.chdir(project_path)
        subprocess.run(cmd, shell=True)


if __name__ == "__main__":
    main()
