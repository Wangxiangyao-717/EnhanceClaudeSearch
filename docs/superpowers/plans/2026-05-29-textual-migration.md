# Textual Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate session_search.py from prompt_toolkit to Textual, feature-complete parity.

**Architecture:** Dual Screen (SearchScreen + DetailScreen) with Textual ScreenStack. Reusable logic extracted to utils.py. CSS in app.tcss.

**Tech Stack:** Python 3.11+, textual, utils.py reuses existing json/os/re/subprocess/unicodedata code.

---

### Task 1: Extract utils.py

**Files:**
- Create: `src/utils.py`
- Modify: `src/session_search.py` (extract functions, keep original working)

Extract reusable functions into `src/utils.py`. These are copy-paste from session_search.py — no logic changes.

- [ ] **Step 1: Create utils.py with config, clipboard, and helper functions**

```python
"""Shared utilities for EnhanceClaudeSearch — config, session I/O, clipboard."""

import json
import os
import platform
import re
import subprocess
import sys
import unicodedata
from datetime import datetime


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
# CJK-aware text width
# ---------------------------------------------------------------------------

def display_width(text):
    w = 0
    for ch in text:
        w += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return w


def wrap_display(text, width):
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


# ---------------------------------------------------------------------------
# Session discovery
# ---------------------------------------------------------------------------

def project_session_dir(project_path=None):
    if project_path is None:
        project_path = os.getcwd()
    abs_path = os.path.abspath(project_path)
    dir_name = abs_path.replace(":", "-").replace("\\", "-").replace("/", "-").replace("_", "-")
    sessions_root = os.path.expanduser("~/.claude/projects")
    session_dir = os.path.join(sessions_root, dir_name)
    if os.path.isdir(session_dir):
        return session_dir, abs_path
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


# ---------------------------------------------------------------------------
# Session searching
# ---------------------------------------------------------------------------

def find_match_snippet(search_text, query, context_chars=10):
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
    filtered = filter_sessions(sessions, query)
    for s in filtered:
        s["match_snippet"] = find_match_snippet(s["search_text"], query)
    return filtered


# ---------------------------------------------------------------------------
# Session detail
# ---------------------------------------------------------------------------

def load_session_messages(session_dir, uuid):
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
```

- [ ] **Step 2: Verify utils.py works standalone**

```bash
python -c "from src.utils import load_config, project_session_dir, build_index, filter_sessions, load_session_messages, load_session_recap; print('All imports OK')"
```

- [ ] **Step 3: Commit**

```bash
git add src/utils.py
git commit -m "extract utils.py from session_search.py"
```

---

### Task 2: Create app.tcss with all styles

**Files:**
- Create: `src/app.tcss`

- [ ] **Step 1: Write app.tcss**

```css
/* --- SearchScreen layout --- */
SearchScreen {
    layout: grid;
    grid-size: 1;
    grid-rows: 1 1 1 1fr auto auto;
}

SearchScreen > Input {
    height: 1;
    margin: 0 1;
}

SearchScreen > Input:focus {
    border: solid #00ffcc;
}

SearchScreen > #status-bar {
    height: 1;
    background: #0a0a1a;
    color: #888888;
    padding: 0 2;
}

SearchScreen > #results {
    border: none;
}

SearchScreen Footer {
    background: #0a0a1a;
    color: #00d4aa;
    dock: bottom;
}

/* --- DetailScreen layout --- */
DetailScreen {
    layout: grid;
    grid-size: 1;
    grid-rows: auto auto 1fr auto;
}

DetailScreen > Static {
    height: auto;
    margin: 0 1;
}

DetailScreen > #detail-status {
    height: 1;
    background: #0a0a1a;
    color: #888888;
    padding: 0 2;
}

DetailScreen > #messages {
    border: none;
}

/* --- ListView items --- */
ListView {
    background: #1a1a2e;
    color: #c0c0c0;
}

ListView > ListItem {
    padding: 0 2;
}

ListView > ListItem.highlighted {
    background: #00d4aa;
    color: #0a0a0a;
    text-style: bold;
}

/* --- Recap section --- */
#recap-box {
    background: #1a1a2e;
    color: #e0e0e0;
    padding: 0 2;
}

#recap-box > Static {
    height: auto;
}

/* --- Header row --- */
#detail-header {
    height: 1;
    color: #666666;
    padding: 0 2;
}

/* --- Separator --- */
#separator {
    height: 1;
    color: #666666;
}
```

- [ ] **Step 2: Commit**

```bash
git add src/app.tcss
git commit -m "add Textual CSS styles"
```

---

### Task 3: Create app.py — App class and entry point

**Files:**
- Create: `src/app.py`

- [ ] **Step 1: Write the App class and main() entry**

```python
"""EnhanceClaudeSearch — Textual TUI for searching Claude Code sessions."""

import os
import subprocess
import sys

from textual.app import App, Screen
from textual.widgets import Footer, Input, ListItem, ListView, Static
from textual.binding import Binding

# Add src to path so utils can be imported
sys.path.insert(0, os.path.dirname(__file__))
from utils import (
    build_index,
    copy_to_clipboard,
    filter_sessions_with_snippets,
    load_config,
    load_session_messages,
    load_session_recap,
    project_session_dir,
    save_config,
    wrap_display,
)


class SearchScreen(Screen):
    """Main search screen: 3 inputs + session list + status."""

    BINDINGS = [
        Binding("right", "push_detail", "详情", key_display="→"),
        Binding("space", "copy_uuid", "复制UUID", key_display="Space"),
    ]

    def compose(self):
        yield Input(placeholder="命令前缀", id="cmd-input")
        yield Input(placeholder="附加参数", id="arg-input")
        yield Input(placeholder="搜索关键词", id="search-input")
        yield ListView(id="results")
        yield Static("", id="status-bar")
        yield Footer()

    def on_mount(self):
        config = self.app.config
        self.query_one("#cmd-input").value = config.get("cmd_prefix", "claude -r")
        self.query_one("#arg-input").value = config.get("cmd_suffix", "")
        self.query_one("#search-input").focus()

        # If launched with a query, pre-fill
        if self.app.initial_query:
            search = self.query_one("#search-input")
            search.value = self.app.initial_query
            self._do_filter(self.app.initial_query)

        self._update_status()
        self._update_config()

    def on_input_changed(self, event: Input.Changed):
        if event.input.id == "cmd-input":
            self.app.config["cmd_prefix"] = event.value
        elif event.input.id == "arg-input":
            self.app.config["cmd_suffix"] = event.value
        elif event.input.id == "search-input":
            self._do_filter(event.value)
        self._update_status()

    def _do_filter(self, query):
        filtered = filter_sessions_with_snippets(self.app.sessions, query)
        lv = self.query_one("#results")

        # Remember which uuid was selected before clearing
        old_uuid = None
        if lv.index is not None and lv.index < len(lv.children):
            old_uuid = lv.children[lv.index].id if hasattr(lv.children[lv.index], 'id') else None

        lv.clear()
        for s in filtered:
            snippet = s.get("match_snippet", "")
            display = f"{s['date_str']}  {s['uuid'][:8]}  {s['first_prompt'][:60]}"
            if snippet:
                display += f"  {snippet}"
            item = ListItem(Static(display), id=s["uuid"])
            lv.append(item)

        # Restore selection or set to 0
        if old_uuid:
            try:
                new_idx = next(i for i, s in enumerate(filtered) if s["uuid"] == old_uuid)
                lv.index = new_idx
            except StopIteration:
                lv.index = 0 if filtered else None
        else:
            lv.index = 0 if filtered else None

        self._update_status()

    def _update_status(self):
        lv = self.query_one("#results")
        total = len(self.app.sessions)
        filtered_count = len(lv.children) if lv.children else 0

        cmd = self.query_one("#cmd-input").value
        arg = self.query_one("#arg-input").value

        preview = ""
        if lv.index is not None and lv.index < len(lv.children):
            item = lv.children[lv.index]
            uuid = item.id or ""
            parts = [p for p in [cmd, uuid[:8], arg] if p]
            preview = f"Run: {' '.join(parts)} | "

        self.query_one("#status-bar").update(
            f"  {filtered_count}/{total} | {preview}"
            f"Tab 切换输入框  Enter 执行  Space 复制UUID  Esc 退出"
        )

    def _update_config(self):
        save_config(self.app.config)

    def action_push_detail(self):
        lv = self.query_one("#results")
        if lv.index is not None and lv.index < len(lv.children):
            uuid = lv.children[lv.index].id
            if uuid:
                self._update_config()
                self.app.push_screen(DetailScreen(uuid))

    def action_copy_uuid(self):
        lv = self.query_one("#results")
        if lv.index is not None and lv.index < len(lv.children):
            uuid = lv.children[lv.index].id
            if uuid:
                copy_to_clipboard(uuid)
                status = self.query_one("#status-bar")
                status.update(f"  已复制: {uuid[:8]}...")
                self.set_timer(2, self._update_status)

    def action_execute(self):
        """Called when Enter is pressed on the ListView."""
        lv = self.query_one("#results")
        if lv.index is not None and lv.index < len(lv.children):
            uuid = lv.children[lv.index].id
            if uuid:
                self._update_config()
                cmd = self.query_one("#cmd-input").value
                arg = self.query_one("#arg-input").value
                parts = [p for p in [cmd, uuid, arg] if p]
                full_cmd = " ".join(parts)
                self.app.exit(result=("run", full_cmd))


class DetailScreen(Screen):
    """Detail view: recap + session info + message list."""

    BINDINGS = [
        Binding("left", "pop_screen", "返回", key_display="←"),
        Binding("escape", "pop_screen", "返回", key_display="Esc"),
    ]

    def __init__(self, uuid):
        super().__init__()
        self.session_uuid = uuid

    def compose(self):
        yield Static("", id="recap-box")
        yield Static("", id="detail-header")
        yield Static("", id="separator")
        yield ListView(id="messages")
        yield Static("", id="detail-status")

    def on_mount(self):
        info = next(
            (s for s in self.app.sessions if s["uuid"] == self.session_uuid), None
        )
        date_str = info["date_str"] if info else "??-?? ??:??"
        uuid_short = self.session_uuid[:8]

        # Load data
        self.messages = load_session_messages(self.app.session_dir, self.session_uuid)
        recap = load_session_recap(self.app.session_dir, self.session_uuid)

        # Recap section
        recap_box = self.query_one("#recap-box")
        if recap and recap.strip():
            term_width = self.size.width
            wrapped = wrap_display(recap.strip(), max(20, term_width - 4))
            recap_display = wrapped[:5]
            if len(wrapped) > 5:
                recap_display[-1] = recap_display[-1][:max(20, term_width - 7)] + "..."
            recap_box.update("\n".join(recap_display))
        else:
            recap_box.display = False

        # Header
        self.query_one("#detail-header").update(
            f"  Session: {uuid_short}    {date_str}    {len(self.messages)} messages"
        )

        # Separator
        self.query_one("#separator").update(f"  {'─' * (self.size.width - 4)}")

        # Messages
        lv = self.query_one("#messages")
        for i, msg in enumerate(self.messages):
            truncated = msg[:self.size.width - 6]
            item = ListItem(Static(f"  {i + 1:>3}. {truncated}"))
            lv.append(item)
        if self.messages:
            lv.index = 0

        self._update_detail_status()

    def on_list_view_highlighted(self, event: ListView.Highlighted):
        self._update_detail_status()

    def _update_detail_status(self):
        lv = self.query_one("#messages")
        idx = lv.index + 1 if lv.index is not None else 0
        total = len(self.messages)
        self.query_one("#detail-status").update(
            f"  {idx}/{total}    ← 返回主界面    ↑↓ 选择    Esc 返回"
        )

    def action_pop_screen(self):
        self.app.pop_screen()


class ClaudeSessionSearch(App):
    """Search Claude Code sessions with Textual TUI."""

    CSS_PATH = "app.tcss"
    TITLE = "Claude Session Search"

    def __init__(self, sessions, session_dir, config, initial_query=""):
        super().__init__()
        self.sessions = sessions
        self.session_dir = session_dir
        self.config = config
        self.initial_query = initial_query

    def on_mount(self):
        self.push_screen(SearchScreen())


def main():
    import shutil

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
    query = " ".join(args) if args else ""

    if list_mode:
        from utils import filter_sessions

        filtered = filter_sessions(sessions, query)
        if not filtered:
            print(f"No sessions matching: {query}")
            sys.exit(0)
        print(f"\n{'DATE':<12} {'UUID':<10} TOPIC")
        print("-" * 80)
        for s in filtered[:20]:
            print(f"{s['date_str']:<12} {s['uuid'][:8]:<10} {s['first_prompt'][:100]}")
        print(f"\n{len(filtered)} match(es).\n")
        sys.exit(0)

    # Interactive TUI
    if query:
        config["last_search"] = query

    app = ClaudeSessionSearch(sessions, session_dir, config, query)
    result = app.run()

    save_config(config)

    print("\033[2J\033[H", end="")
    if result and result[0] == "run":
        cmd = result[1]
        print(f"Running: {cmd}")
        os.chdir(project_path)
        subprocess.run(cmd, shell=True)
    else:
        print("Cancelled.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify syntax**

```bash
python -c "import ast; ast.parse(open('src/app.py', encoding='utf-8').read()); print('Syntax OK')"
```

- [ ] **Step 3: Commit**

```bash
git add src/app.py
git commit -m "add Textual app: SearchScreen + DetailScreen + entry point"
```

---

### Task 4: Update launcher scripts to point to app.py

**Files:**
- Modify: `claudes.ps1` (line 3)

- [ ] **Step 1: Update claudes.ps1**

Change the script path from `session_search.py` to `app.py`:

```powershell
$ErrorActionPreference = 'Stop'
$ScriptRoot = $PSScriptRoot
$ScriptPath = Join-Path $ScriptRoot 'src\app.py'

& python $ScriptPath @args
exit $LASTEXITCODE
```

- [ ] **Step 2: Test that the launcher still works**

```bash
python src/app.py --list 2>&1
```

Expected: list mode output showing session entries, no errors.

- [ ] **Step 3: Commit**

```bash
git add claudes.ps1
git commit -m "update launcher to point to app.py"
```

---

### Task 5: Integration test

**Files:**
- Verify: `src/app.py` (end-to-end)

- [ ] **Step 1: Test list mode**

```bash
python src/app.py --list
```

Expected: Shows session table with DATE / UUID / TOPIC columns.

- [ ] **Step 2: Test list mode with keyword**

```bash
python src/app.py --list python
```

Expected: Only sessions matching "python" are shown.

- [ ] **Step 3: Test interactive TUI launch**

```bash
timeout 3 python src/app.py 2>&1; echo "Exit: $?"
```

Expected: No traceback, TUI renders, exit code 124 (timeout killed it).

- [ ] **Step 4: Commit final adjustments if any**

```bash
git add -A && git commit -m "final integration fixes for Textual migration"
```

---

### Task 6: Install textual dependency and test live

- [ ] **Step 1: Install textual**

```bash
pip install textual
```

- [ ] **Step 2: Run from terminal**

```bash
python src/app.py
```

Expected: Interactive TUI with three input fields, keyboard navigation, detail view on → key. Verify all features:
- Input field focus switching (Tab)
- Search filtering
- ListView navigation (↑↓)
- Detail view enter/exit (→ / ←)
- UUID copy (Space on ListView)
- Command execution (Enter on ListView)
- Config persistence (quit and re-launch)

- [ ] **Step 3: Commit and push**

```bash
git add -A && git commit -m "Textual migration complete" && git push -u origin feature/textual-migration
```
