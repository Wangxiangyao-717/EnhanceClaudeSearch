# EnhanceClaudeSearch

Claude Code 会话全文搜索工具，弥补 `claude -r` 只能按标题搜索的不足。

基于 [Textual](https://textual.textualize.io/) 构建。

## 功能

- 扫描 `~/.claude/projects/` 下的所有 session，建立全文索引
- 三个常驻标签的输入框：**Cmd**、**Arg**、**Search**
- 焦点始终在输入框，随时打字过滤，↑↓ 直接浏览结果
- Enter 拼接 `{Cmd} {UUID} {Arg}` 执行命令
- → 进入详情页，浏览全部用户消息和 recap
- Cmd 和 Arg 内容自动记忆

## 安装

双击 `init.bat`，或在终端执行：

```powershell
.\init.ps1
```

这会把项目目录加入用户 PATH，之后任意目录都能使用 `claudes`。

## 使用

```bash
# 交互式搜索
claudes

# 预填搜索词
claudes keyword

# 非交互列表模式
claudes --list keyword
```

### 主界面操作

| 按键 | 功能 |
|------|------|
| Tab / Shift+Tab | 切换输入框（Cmd → Arg → Search） |
| ↑↓ | 浏览搜索结果 |
| Enter | 执行 `{Cmd} {UUID} {Arg}` |
| → | 进入详情页 |
| Ctrl+Y | 复制 UUID 到剪贴板 |
| Esc | 退出 |

### 命令拼接规则

三个输入框和选中 session 的 UUID 按空格拼接：

```
{Cmd} {UUID} {Arg}
```

例如 Cmd 填 `claude -r`、Arg 填 `--resume`，选中 UUID 为 `abc12345`，按 Enter 执行：

```bash
claude -r abc12345 --resume
```

### 详情页操作

| 按键 | 功能 |
|------|------|
| ↑↓ | 选择消息 |
| ← / Esc | 返回主界面 |

## 自定义快捷命令名

默认命令名是 `claudes`，想改成其他名字只需重命名两个文件：

```powershell
# 以改名为 ccs 为例
Rename-Item claudes.cmd ccs.cmd
Rename-Item claudes.ps1 ccs.ps1
```

改完之后 `ccs` 就是新的快捷命令了。

## 依赖

- Python 3.11+
- textual

```bash
pip install textual
```
