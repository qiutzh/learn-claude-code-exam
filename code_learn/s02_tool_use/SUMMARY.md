# 项目摘要（SUMMARY）

> 生成日期：自动生成。本摘要基于目录中实际存在的文件。

## 源文件状态

| 请求读取的文件 | 是否存在 | 说明 |
|---------------|---------|------|
| README.md     | ❌ 不存在 | 目录中只有中文版 `README.zh.md`，本摘要基于它生成 |
| requirements.txt | ❌ 不存在 | 目录中没有任何依赖清单文件 |

## 项目概述（来自 README.zh.md）

- **项目名称**：s02: Tool Use（工具使用）
- **所属系列**：learn-claude-code 教程的第二章（s01 → s02 → s03）
- **核心主题**：工具分发（Tool Dispatch）
- **口号**："加一个工具，只加一个 handler" — 循环不用动，新工具注册进 dispatch map 就行。

### 背景

s01 的 Agent 只有一个 `bash` 工具，读文件要 `cat`，写文件要 `echo "..." > file.py`，改文件要 `sed`，多了一层翻译，浪费 token 还容易拼错。

### 核心设计

- 工具数量从 1 个扩展到 5 个：`bash`、`read_file`、`write_file`、`edit_file`、`glob`
- 加一个工具只需两步：
  1. 在 `TOOLS` 数组里加一条 JSON schema 描述
  2. 在 `TOOL_HANDLERS` 字典里加一行映射
- 主循环保持不变：`while True` + `tool_use` block 判断，只用 `TOOL_HANDLERS[block.name]()` 查表分发替换硬编码的 `run_bash()`
- 模型可一次返回多个 tool_use，按原始顺序逐个执行
- 文件类工具通过 `safe_path` 校验保护，但 `bash` 不受限制

### 相对 s01 的变更

| 组件 | 之前 (s01) | 之后 (s02) |
|------|-----------|-----------|
| 工具数量 | 1 (bash) | 5 (+read, write, edit, glob) |
| 工具执行 | 硬编码 `run_bash()` | TOOL_HANDLERS 查表分发 |
| 路径安全 | 无 | safe_path 校验（仅 file tools） |
| 循环 | `while True` + `tool_use` block | 与 s01 完全一致 |

### 后续方向

s03 Permission：在工具执行前加一道门 —— 这个操作安全吗？需要用户批准吗？