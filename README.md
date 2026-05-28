# EnhanceClaudeSearch

Claude Code 会话全文搜索工具，弥补 `claude -r` 只能按标题搜索的不足。

## 功能

- 扫描 `~/.claude/projects/` 下的所有 session，建立全文索引
- 三个输入框：**命令前缀**、**附加参数**、**搜索关键词**
- 输入即过滤，↑↓ 选择，Enter 执行命令，Space 复制 UUID
- 选中后按 → 进入详情页，浏览该会话的全部用户消息
- 命令前缀和附加参数自动记忆

## 安装

双击 `init.bat`，或在终端执行：

```powershell
.\init.ps1
```

这会把项目目录加入用户 PATH，之后任意目录都能使用 `csch`。

## 使用

```bash
# 交互式搜索
csch

# 预填搜索词
csch keyword

# 非交互列表模式
csch --list keyword
```

### 主界面

- `Tab` / `Shift+Tab` — 切换输入框焦点
- `↑↓` — 选择会话
- `Enter` — 按 `{Cmd} {UUID} {Arg}` 拼接并执行命令（见下方说明）
- `Space` — 复制 UUID 到剪贴板
- `→` — 进入详情页
- `Esc` — 退出

### Enter 执行的命令是怎样拼出来的

界面顶部的三个输入框和选中的 session UUID 按顺序拼接：

```
{Cmd} {UUID} {Arg}
```

例如你填写：

| 输入框 | 内容 |
|--------|------|
| Cmd | `claude -r` |
| Arg | `--resume` |

选中 UUID 为 `abc12345` 的会话，按 Enter 后执行的就是：

```bash
claude -r abc12345 --resume
```

三个部分之间用空格连接，某一部分为空则自动跳过。你也可以把 Cmd 改成 `dpsk -r` 或 `codex --resume` 等任意命令。

### 详情页

- `↑↓` — 选择消息
- `←` 或 `Esc` — 返回主界面

## 自定义快捷命令名

默认命令名是 `csch`，想改成其他名字（比如 `search`）只需重命名两个文件：

```powershell
# 在项目目录下执行，以改名为 search 为例
Rename-Item csch.cmd search.cmd
Rename-Item csch.ps1 search.ps1
```

改完之后 `search` 就是新的快捷命令了。原理很简单：

- **PowerShell** 中，输入 `search` 会匹配 `search.ps1`
- **CMD** 中，输入 `search` 会匹配 `search.cmd`，它会调用 `search.ps1`

两个文件必须同名（除了扩展名），放在一起即可。

## 依赖

- Python 3.11+
- prompt_toolkit >= 3.0

```bash
pip install prompt_toolkit
```
