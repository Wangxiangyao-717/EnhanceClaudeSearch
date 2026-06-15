"""EnhanceClaudeSearch — Textual TUI for searching Claude Code sessions."""

import os
import subprocess
import sys

from textual.app import App, Screen
from textual.containers import Horizontal
from textual.widgets import Footer, Input, ListItem, ListView, Static
from textual.binding import Binding

sys.path.insert(0, os.path.dirname(__file__))
from utils import (
    build_index, copy_to_clipboard, filter_sessions_with_snippets,
    load_config, load_session_messages, load_session_recap,
    project_session_dir, save_config, wrap_display,
)


class SearchScreen(Screen):
    BINDINGS = [
        Binding("escape", "quit", "退出"),
        Binding("tab", "focus_next", "切换", show=False),
        Binding("shift+tab", "focus_previous", "切换", show=False),
    ]

    def compose(self):
        yield Horizontal(
            Static("Cmd:", classes="field-label"),
            Input(placeholder="", id="cmd-input", compact=True, select_on_focus=False, classes="field-input"),
            classes="input-row",
        )
        yield Horizontal(
            Static("Arg:", classes="field-label"),
            Input(placeholder="", id="arg-input", compact=True, select_on_focus=False, classes="field-input"),
            classes="input-row",
        )
        yield Horizontal(
            Static("Search:", classes="field-label"),
            Input(placeholder="", id="search-input", compact=True, select_on_focus=False, classes="field-input"),
            classes="input-row",
        )
        yield ListView(id="results")
        yield Static("", id="status-bar")
        yield Footer()

    async def on_mount(self):
        config = self.app.config
        self._init = True
        self._filter_generation = 0
        self.query_one("#cmd-input").value = config.get("cmd_prefix", "claude -r")
        self.query_one("#arg-input").value = config.get("cmd_suffix", "")
        if self.app.initial_query:
            self.query_one("#search-input").value = self.app.initial_query
        self._init = False
        await self._do_filter(self.query_one("#search-input").value)
        self.query_one("#search-input").focus()
        self._update_status()

    async def on_input_changed(self, event: Input.Changed):
        if getattr(self, "_init", False):
            return
        if event.input.id == "cmd-input":
            self.app.config["cmd_prefix"] = event.value
        elif event.input.id == "arg-input":
            self.app.config["cmd_suffix"] = event.value
        elif event.input.id == "search-input":
            await self._do_filter(event.value)
        self._update_status()

    def _focusables(self):
        return [self.query_one(f"#{i}") for i in ["cmd-input", "arg-input", "search-input"]]

    def _cycle_focus(self, step):
        inputs = self._focusables()
        focused = self.focused
        try:
            idx = inputs.index(focused)
            nxt = inputs[(idx + step) % len(inputs)]
        except ValueError:
            nxt = inputs[0]
        nxt.focus()

    def on_key(self, event):
        key = event.key
        if key == "down":
            self._move_selection(1)
            event.stop()
        elif key == "up":
            self._move_selection(-1)
            event.stop()
        elif key == "enter":
            self._execute_selected()
            event.stop()
        elif key == "ctrl+y":
            self.copy_selected_uuid()
            event.stop()
        elif key == "right":
            self.open_selected_detail()
            event.stop()
        elif key == "left":
            event.stop()

    def on_list_view_selected(self, event: ListView.Selected):
        event.stop()
        self._execute_selected()

    def on_list_view_highlighted(self, event: ListView.Highlighted):
        if event.list_view.id == "results":
            self._update_status()

    async def _do_filter(self, query):
        self._filter_generation += 1
        generation = self._filter_generation
        filtered = filter_sessions_with_snippets(self.app.sessions, query)
        lv = self.query_one("#results")
        old_uuid = None
        if lv.index is not None and lv.index < len(lv.children):
            old_uuid = lv.children[lv.index].id

        await lv.clear()
        if generation != self._filter_generation:
            return

        items = []
        for s in filtered:
            snippet = s.get("match_snippet", "")
            topic = s.get("ai_title") or s["first_prompt"]
            line = f"{s['date_str']}  {s['uuid'][:8]}  {topic[:60]}"
            if snippet:
                line += f"  {snippet}"
            items.append(ListItem(Static(line), id=f"s-{s['uuid']}"))

        if items:
            await lv.extend(items)
        if generation != self._filter_generation:
            return

        if old_uuid:
            try:
                new_idx = next(i for i, s in enumerate(filtered) if f"s-{s['uuid']}" == old_uuid)
                lv.index = new_idx
            except StopIteration:
                lv.index = 0 if filtered else None
        else:
            lv.index = 0 if filtered else None
        self._update_status()

    def _selected_uuid(self):
        lv = self.query_one("#results")
        if lv.index is not None and lv.index < len(lv.children):
            raw_id = lv.children[lv.index].id or ""
            return raw_id[2:] if raw_id.startswith("s-") else raw_id
        return None

    def _move_selection(self, step):
        lv = self.query_one("#results")
        count = len(lv.children)
        if count == 0:
            return
        current = 0 if lv.index is None else lv.index
        lv.index = max(0, min(count - 1, current + step))
        self._update_status()

    def _execute_selected(self):
        uuid = self._selected_uuid()
        if uuid:
            save_config(self.app.config)
            cmd = self.query_one("#cmd-input").value
            arg = self.query_one("#arg-input").value
            parts = [p for p in [cmd, uuid, arg] if p]
            self.app.exit(result=("run", " ".join(parts)))

    def _update_status(self):
        lv = self.query_one("#results")
        total = len(self.app.sessions)
        n = len(lv.children) if lv.children else 0
        cmd = self.query_one("#cmd-input").value
        arg = self.query_one("#arg-input").value
        preview = ""
        uuid = self._selected_uuid()
        if uuid:
            parts = [p for p in [cmd, uuid[:8], arg] if p]
            preview = f"  -> {' '.join(parts)}"
        self.query_one("#status-bar").update(
            f"{n}/{total}{preview}   ↑↓浏览  Enter执行  Ctrl+Y复制  →详情"
        )

    def action_focus_next(self):
        self._cycle_focus(1)

    def action_focus_previous(self):
        self._cycle_focus(-1)

    def open_selected_detail(self):
        uuid = self._selected_uuid()
        if uuid:
            save_config(self.app.config)
            self.app.push_screen(DetailScreen(uuid))

    def copy_selected_uuid(self):
        uuid = self._selected_uuid()
        if uuid:
            copy_to_clipboard(uuid)
            self.query_one("#status-bar").update(f"Copied: {uuid[:8]}...")
            self.set_timer(2, self._update_status)

    def action_quit(self):
        self.app.exit()


class DetailScreen(Screen):
    BINDINGS = [
        Binding("left", "pop_screen", "返回", show=False),
        Binding("escape", "pop_screen", "返回"),
    ]

    def __init__(self, session_uuid):
        super().__init__()
        self.session_uuid = session_uuid

    def compose(self):
        yield Static("", id="recap-box")
        yield Static("", id="detail-header")
        yield Static("", id="separator")
        yield Static("", id="detail-status")
        yield ListView(id="messages")
        yield Footer()

    def on_mount(self):
        info = next((s for s in self.app.sessions if s["uuid"] == self.session_uuid), None)
        date_str = info["date_str"] if info else "??-?? ??:??"
        uuid_short = self.session_uuid[:8]
        self.messages = load_session_messages(self.app.session_dir, self.session_uuid)
        recap = load_session_recap(self.app.session_dir, self.session_uuid)
        w = self.app.size.width

        recap_box = self.query_one("#recap-box")
        if recap and recap.strip():
            wrapped = wrap_display(recap.strip(), max(20, w - 4))
            disp = wrapped[:5]
            if len(wrapped) > 5:
                disp[-1] = disp[-1][: max(20, w - 7)] + "..."
            recap_box.update("\n".join(disp))
        else:
            recap_box.display = False

        self.query_one("#detail-header").update(f"Session: {uuid_short}  {date_str}  {len(self.messages)} msgs")
        self.query_one("#separator").update("─" * (w - 2))

        lv = self.query_one("#messages")
        for i, msg in enumerate(self.messages):
            lv.append(ListItem(Static(f"{i + 1:>3}. {msg[:w - 6]}")))
        if self.messages:
            lv.index = 0
        lv.focus()
        self._update_detail_status()

    def on_list_view_highlighted(self, event: ListView.Highlighted):
        if event.list_view.id == "messages":
            self._update_detail_status()

    def _update_detail_status(self):
        lv = self.query_one("#messages")
        idx = lv.index + 1 if lv.index is not None else 0
        self.query_one("#detail-status").update(f"{idx}/{len(self.messages)}")

    def action_pop_screen(self):
        self.app.pop_screen()


class ClaudeSessionSearch(App):
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
            topic = s.get("ai_title") or s["first_prompt"]
            print(f"{s['date_str']:<12} {s['uuid'][:8]:<10} {topic[:100]}")
        print(f"\n{len(filtered)} match(es).\n")
        sys.exit(0)
    app = ClaudeSessionSearch(sessions, session_dir, config, query)
    result = app.run()
    save_config(config)
    print("\033[2J\033[H", end="")
    if result and isinstance(result, tuple) and result[0] == "run":
        cmd = result[1]
        print(f"Running: {cmd}")
        os.chdir(project_path)
        subprocess.run(cmd, shell=True)
    else:
        print("Cancelled.")


if __name__ == "__main__":
    main()
