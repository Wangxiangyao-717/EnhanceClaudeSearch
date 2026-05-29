# Textual 迁移设计

日期: 2026-05-29
分支: `feature/textual-migration`
审阅: Codex (3 项发现已修正)

## 目标

将 `session_search.py` 从 prompt_toolkit 迁移到 Textual，功能对等，不增不减。

## 动机

当前 831 行手写 TUI：虚拟滚动、CJK 宽度计算、焦点管理、双视图切换。Textual 有现成的 Input、ListView、ScreenStack，CSS 布局，能砍掉大量手写代码。

## 架构

双 Screen 结构，ScreenStack 管理导航。

```
src/
  app.py              # App 入口 + SearchScreen + DetailScreen
  utils.py            # 现有工具函数（config、session、clipboard）
  app.tcss            # 全部样式
```

`claudes.cmd` / `claudes.ps1` 入口改为 `python app.py`。

### SearchScreen

- 3 个 `Input` 组件：cmd_prefix、cmd_suffix、search_query
- 1 个 `ListView`：搜索结果，每项显示 date + uuid + topic + match_snippet
- 1 个 `Static` 状态栏：匹配数 / 命令预览 / 操作提示（**不是 Footer，Footer 只显示按键绑定**）
- 1 个 `Footer`：自动显示当前焦点 widget 的绑定键
- `Input.Changed` → 过滤后用 `clear()` + `extend()` 更新 ListView，并恢复 `index` 为有效值
- 选中项高亮自动跟随
- ListView 自带虚拟滚动（Textual 内置）
- CSS grid 布局：三行固定高度 Input + 自适应 ListView + 固定 Static + 固定 Footer

### DetailScreen

- 顶部固定区域：recap 文本（最多 5 行自动换行）
- 中间 session 信息栏 + 分隔线
- `ListView`：用户消息列表，带序号
- `Static` 状态栏：序号/总数 + 操作提示
- CSS grid 布局：固定 Top + 自适应 ListView + 固定 Static
- Textual 内置 CJK 宽度处理，删除 `display_width()` / `wrap_display()`

## 组件映射

| 原实现 | Textual |
|--------|---------|
| 手动渲染三个输入行 | `Input` × 3 |
| 手动渲染结果 + 虚拟滚动 | `ListView` + `ListItem` |
| 手动渲染状态栏 | `Static`（状态文本）+ `Footer`（按键提示）|
| `detail_mode` flag | `push_screen` / `pop_screen` |
| `STYLE` 字典 | `app.tcss` CSS |
| `display_width()` / `wrap_display()` | 删除 |

## 按键映射（修正：区分 Input 焦点和 ListView 焦点）

| 键 | Input 有焦点 | ListView 有焦点 | DetailScreen |
|----|-------------|----------------|-------------|
| ↑↓ | 无（Input 不响应）| ListView 原生导航 | ListView 原生导航 |
| → | 无 | push DetailScreen | — |
| ← | — | — | pop_screen |
| Tab | 切到下一个 Input/ListView | 切到下一个 Input | — |
| Enter | 无 | 执行 `{cmd} {uuid} {arg}` | — |
| Space | 输入空格 | 复制 UUID | — |
| Esc | 取消焦点 | app.exit | pop_screen |

## 数据流（修正：ListView API）

```
Input.Changed → query → filter_sessions() → list_view.clear() + list_view.extend(items) + list_view.index = valid_idx
ListView 选中 + → → push_screen(DetailScreen(uuid))
DetailScreen.on_mount → load_session_messages() + load_session_recap()
```

## 复用代码

以下模块从原有代码直接搬入 `utils.py`，不做改动：
- `load_config()` / `save_config()` / `DEFAULT_CONFIG`
- `copy_to_clipboard()`
- `project_session_dir()`
- `build_index()` / `extract_session_info()`
- `filter_sessions()` / `filter_sessions_with_snippets()`
- `find_match_snippet()`
- `load_session_messages()` / `load_session_recap()`

## 不做的

- 不加新功能
- 不改 claudes.cmd / claudes.ps1（除了入口文件名）
- 不删原有 `session_search.py`（保留到验证完成）

## 依赖

- `textual` — pip install textual
- 不再依赖 `prompt-toolkit`
