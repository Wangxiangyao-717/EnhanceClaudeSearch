"""EnhanceClaudeSearch — Textual TUI for searching Claude Code sessions."""

import os
import subprocess
import sys

from textual.app import App, Screen
from textual.widgets import Footer, Input, ListItem, ListView, Static
from textual.binding import Binding

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
        Binding("right", "push_detail", "详情"),
        Binding("space", "do_space", "复制UUID"),
        Binding("enter", "do_enter", "执行命令"),
    ]

    def compose(self):
        yield Input(placeholder="命令前缀", id="cmd-input")
        yield Input(placeholder="附加参数", id="arg-input")
        yield Input(placeholder="搜索关键词", id="search-input")
        yield Static("", id="status-bar")
        yield ListView(id="results")
        yield Footer()

    def on_mount(self):
        config = self.app.config
        self.query_one("#cmd-input").value = config.get("cmd_prefix", "claude -r")
        self.query_one("#arg-input").value = config.get("cmd_suffix", "")

        if self.app.initial_query:
            search = self.query_one("#search-input")
            search.value = self.app.initial_query
            self._do_filter(self.app.initial_query)
        else:
            self._do_filter("")

        self.query_one("#search-input").focus()
        self._update_status()

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

        old_uuid = None
        if lv.index is not None and lv.index < len(lv.children):
            item = lv.children[lv.index]
            old_uuid = item.id if item.id else None

        lv.clear()
        for s in filtered:
            snippet = s.get("match_snippet", "")
            line = f"{s['date_str']}  {s['uuid'][:8]}  {s['first_prompt'][:60]}"
            if snippet:
                line += f"  {snippet}"
            lv.append(ListItem(Static(line), id=f"s-{s['uuid']}"))

        if old_uuid:
            try:
                new_idx = next(
                    i for i, s in enumerate(filtered)
                    if f"s-{s['uuid']}" == old_uuid
                )
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
            preview = f" → {' '.join(parts)}"
        self.query_one("#status-bar").update(
            f"{n}/{total}{preview}   →详情  Enter执行  Space复制  Esc退出"
        )

    def action_do_space(self):
        if isinstance(self.focused, Input):
            self.focused.insert_text_at_cursor(" ")
            return
        uuid = self._selected_uuid()
        if uuid:
            copy_to_clipboard(uuid)
            self.query_one("#status-bar").update(f"已复制 {uuid[:8]}...")
            self.set_timer(2, self._update_status)

    def action_do_enter(self):
        if isinstance(self.focused, Input):
            return
        uuid = self._selected_uuid()
        if uuid:
            save_config(self.app.config)
            cmd = self.query_one("#cmd-input").value
            arg = self.query_one("#arg-input").value
            parts = [p for p in [cmd, uuid, arg] if p]
            self.app.exit(result=("run", " ".join(parts)))

    def action_push_detail(self):
        if isinstance(self.focused, Input):
            return
        uuid = self._selected_uuid()
        if uuid:
            save_config(self.app.config)
            self.app.push_screen(DetailScreen(uuid))


class DetailScreen(Screen):
    """Detail view: recap + session info + message list."""

    BINDINGS = [
        Binding("left", "pop_screen", "返回"),
        Binding("escape", "pop_screen", "退出"),
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
        info = next(
            (s for s in self.app.sessions if s["uuid"] == self.session_uuid), None
        )
        date_str = info["date_str"] if info else "??-?? ??:??"
        uuid_short = self.session_uuid[:8]

        self.messages = load_session_messages(
            self.app.session_dir, self.session_uuid
        )
        recap = load_session_recap(self.app.session_dir, self.session_uuid)

        w = self.app.size.width

        recap_box = self.query_one("#recap-box")
        if recap and recap.strip():
            wrapped = wrap_display(recap.strip(), max(20, w - 4))
            recap_display = wrapped[:5]
            if len(wrapped) > 5:
                recap_display[-1] = recap_display[-1][: max(20, w - 7)] + "..."
            recap_box.update("\n".join(recap_display))
        else:
            recap_box.display = False

        self.query_one("#detail-header").update(
            f"Session: {uuid_short}  {date_str}  {len(self.messages)} messages"
        )
        self.query_one("#separator").update("─" * (w - 2))

        lv = self.query_one("#messages")
        for i, msg in enumerate(self.messages):
            truncated = msg[: w - 6]
            lv.append(ListItem(Static(f"{i + 1:>3}. {truncated}")))
        if self.messages:
            lv.index = 0

        self._update_detail_status()

    def on_list_view_highlighted(self, event: ListView.Highlighted):
        self._update_detail_status()

    def _update_detail_status(self):
        lv = self.query_one("#messages")
        idx = lv.index + 1 if lv.index is not None else 0
        total = len(self.messages)
        self.query_one("#detail-status").update(f"{idx}/{total}")

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
            print(f"{s['date_str']:<12} {s['uuid'][:8]:<10} {s['first_prompt'][:100]}")
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
