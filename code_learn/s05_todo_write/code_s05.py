#!/usr/bin/env python3
"""
s05_todo_write.py - TodoWrite

模型通过 TodoManager 跟踪自己的进度。连续三轮没有更新后，
harness 会在工具结果旁追加一条提醒。

    +----------+      +-------+      +--------------+
    |   User   | ---> |  LLM  | ---> | Tools        |
    |  prompt  |      |       |      | + todo_write |
    +----------+      +---^---+      +------+-------+
                          |                 | update
                          |          +------v----------+
                          |          | TodoManager     |
                          |          | [ ] pending     |
                          |          | [>] in progress |
                          |          | [x] completed   |
                          |          +------+----------+
                          | tool_result     |
                          +-----------------+

              rounds_since_todo >= 3 -> add <reminder>
"""

import ast
import json
import os
import re
import subprocess
from pathlib import Path

try:
    import readline

    readline.parse_and_bind('set bind-tty-special-chars off')
except ImportError:
    pass

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv(override=True)
if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

WORKDIR = Path.cwd()
client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))
MODEL = os.environ["MODEL_ID"]

# s05 变更：SYSTEM 提示词增加规划指引
ENVIRONMENT_PROMPT = (
    "Windows：bash 工具通过 cmd.exe 运行；请使用 cmd.exe 语法，而不是 Unix "
    "Bash 或 PowerShell 语法，并优先使用专用文件工具进行文件操作"
    if os.name == "nt"
    else "类 Unix 环境：bash 工具运行系统 shell"
)
SYSTEM = (
    f"你是一个位于 {WORKDIR} 的编程 agent。环境：{ENVIRONMENT_PROMPT}。"
    "在开始任何多步骤任务之前，使用 todo_write 规划你的步骤。"
    "随着进展更新状态。"
)


# -- 来自 s02-s04 的工具实现 --

def run_bash(command: str) -> str:
    try:
        r = subprocess.run(command, shell=True, cwd=WORKDIR,
                           capture_output=True, text=True, errors="replace", timeout=120)
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(无输出)"
    except subprocess.TimeoutExpired:
        return "错误：超时（120s）"


def run_read(path: str, limit: int | None = None) -> str:
    try:
        lines = (WORKDIR / path).resolve().read_text(encoding="utf-8").splitlines()
        if limit and limit < len(lines):
            lines = lines[:limit] + [f"... （另有 {len(lines) - limit} 行）"]
        return "\n".join(lines)
    except Exception as e:
        return f"错误：{e}"


def run_write(path: str, content: str) -> str:
    try:
        file_path = (WORKDIR / path).resolve()
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        return f"已写入 {len(content)} 字节到 {path}"
    except Exception as e:
        return f"错误：{e}"


def run_edit(path: str, old_text: str, new_text: str) -> str:
    try:
        file_path = (WORKDIR / path).resolve()
        text = file_path.read_text(encoding="utf-8")
        if old_text not in text:
            return f"错误：在 {path} 中未找到文本"
        file_path.write_text(text.replace(old_text, new_text, 1), encoding="utf-8")
        return f"已编辑 {path}"
    except Exception as e:
        return f"错误：{e}"


def run_glob(pattern: str) -> str:
    import glob as g
    try:
        matches = sorted({
            match for match in g.glob(
                pattern, root_dir=WORKDIR, recursive=True)
            if (WORKDIR / match).resolve().is_relative_to(WORKDIR)
        })
        shown = matches[:200]
        if len(matches) > 200:
            shown.append("... （更多匹配已省略；请缩小匹配模式）")
        return "\n".join(shown) if shown else "(无匹配)"
    except Exception as e:
        return f"错误：{e}"


# -- s05 新增：由模型更新的结构化状态 --

class TodoManager:
    def __init__(self):
        self.items: list[dict] = []

    def update(self, todos: list | str) -> str:
        if isinstance(todos, str):
            try:
                todos = json.loads(todos)
            except json.JSONDecodeError:
                try:
                    todos = ast.literal_eval(todos)
                except (SyntaxError, ValueError) as e:
                    raise ValueError("todos 必须是列表或 JSON 数组字符串") from e

        if not isinstance(todos, list):
            raise ValueError("todos 必须是列表")
        if len(todos) > 20:
            raise ValueError("最多允许 20 个 todo")

        validated = []
        in_progress_count = 0
        for index, todo in enumerate(todos):
            if not isinstance(todo, dict):
                raise ValueError(f"todos[{index}] 必须是对象")

            content = str(todo.get("content", "")).strip()
            status = str(todo.get("status", "pending")).lower()
            if not content:
                raise ValueError(f"todos[{index}] 需要 content")
            if status not in ("pending", "in_progress", "completed"):
                raise ValueError(f"todos[{index}] 的状态 '{status}' 无效")
            if status == "in_progress":
                in_progress_count += 1
            validated.append({"content": content, "status": status})

        if in_progress_count > 1:
            raise ValueError("同一时间只能有一个 todo 处于 in_progress 状态")

        self.items = validated
        return self.render()  # todo

    def render(self) -> str:
        if not self.items:
            return "没有 todo。"

        lines = []
        for todo in self.items:
            marker = {
                "pending": "[ ]",
                "in_progress": "[>]",
                "completed": "[x]",
            }[todo["status"]]
            lines.append(f"{marker} {todo['content']}")

        done = sum(todo["status"] == "completed" for todo in self.items)
        lines.append(f"\n（{done}/{len(self.items)} 已完成）")
        return "\n".join(lines)


TODO = TodoManager()


def run_todo_write(todos: list | str) -> str:
    try:
        output = TODO.update(todos)
    except ValueError as e:
        return f"错误：{e}"
    print(f"\n\033[33m## 当前任务\033[0m\n{output}")
    return output


TOOLS = [
    {"name": "bash", "description": "运行一个 shell 命令。",
     "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
    {"name": "read_file", "description": "读取文件内容。",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}},
                      "required": ["path"]}},
    {"name": "write_file", "description": "将内容写入文件。",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                      "required": ["path", "content"]}},
    {"name": "edit_file", "description": "在文件中替换一次精确文本。",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"},
                                                       "new_text": {"type": "string"}},
                      "required": ["path", "old_text", "new_text"]}},
    {"name": "glob", "description": "查找匹配 glob 模式的文件；** 表示递归匹配。",
     "input_schema": {"type": "object", "properties": {"pattern": {"type": "string"}}, "required": ["pattern"]}},
    # s05：新工具
    {"name": "todo_write", "description": "为当前编程会话创建和管理任务列表。",
     "input_schema": {"type": "object", "properties": {"todos": {"type": "array", "maxItems": 20,
                                                                 "items": {"type": "object", "properties": {
                                                                     "content": {"type": "string", "minLength": 1},
                                                                     "status": {"type": "string",
                                                                                "enum": ["pending", "in_progress",
                                                                                         "completed"]}},
                                                                           "required": ["content", "status"]}}},
                      "required": ["todos"]}},
]

TOOL_HANDLERS = {
    "bash": run_bash, "read_file": run_read, "write_file": run_write,
    "edit_file": run_edit, "glob": run_glob, "todo_write": run_todo_write,
}

# -- 来自 s04 的 Hook 系统 --

HOOKS = {"UserPromptSubmit": [], "PreToolUse": [], "PostToolUse": [], "Stop": []}


def register_hook(event: str, callback):
    HOOKS[event].append(callback)


def trigger_hooks(event: str, *args):
    for callback in HOOKS[event]:
        result = callback(*args)
        if result is not None:
            return result
    return None


DENY_LIST = ["rm -rf /", "sudo", "shutdown", "reboot", "mkfs", "dd if="]
DESTRUCTIVE_COMMAND_WORD = re.compile(
    r"(?i)(?:^|[;&|()\n])\s*(?:rm|del)(?=\s|$|[;&|()])"
)
DESTRUCTIVE = ["rm ", "> /etc/", "chmod 777"]


def contains_destructive_command(command: str) -> bool:
    return bool(DESTRUCTIVE_COMMAND_WORD.search(command))


def permission_hook(block):
    """PreToolUse：s03 的权限逻辑，注册为 s04 hook。"""
    if block.name == "bash":
        command = block.input.get("command", "")
        for pattern in DENY_LIST:
            if pattern in command:
                print(f"\n\033[31m[已阻止] '{pattern}'\033[0m")
                return "已被拒绝列表拒绝"
        if contains_destructive_command(command) or any(
                keyword in command for keyword in DESTRUCTIVE
        ):
            print(f"\n\033[33m[权限] 潜在破坏性命令\033[0m")
            print(f"   工具：{block.name}({block.input})")
            choice = input("   允许？[y/N] ").strip().lower()
            if choice not in ("y", "yes"):
                return "已被用户拒绝"
    if block.name in ("read_file", "write_file", "edit_file"):
        path = block.input.get("path", "")
        if not (WORKDIR / path).resolve().is_relative_to(WORKDIR):
            print(f"\n\033[33m[权限] 访问工作区之外\033[0m")
            print(f"   工具：{block.name}({block.input})")
            choice = input("   允许？[y/N] ").strip().lower()
            if choice not in ("y", "yes"):
                return "已被用户拒绝"
    return None


def log_hook(block):
    """PreToolUse：记录每一次工具调用。"""
    args_preview = str(list(block.input.values())[:2])[:60]
    print(f"\033[90m[HOOK] {block.name}({args_preview})\033[0m")
    return None


def large_output_hook(block, output):
    """PostToolUse：在输出过大时给出警告。"""
    if len(str(output)) > 100000:
        print(f"\033[33m[HOOK] 来自 {block.name} 的大输出：{len(str(output))} 字符\033[0m")
    return None


def context_inject_hook(query: str):
    """UserPromptSubmit：记录工作目录。"""
    print(f"\033[90m[HOOK] UserPromptSubmit：工作目录为 {WORKDIR}\033[0m")
    return None


def summary_hook(messages: list):
    """Stop：打印工具调用次数。"""
    tool_count = sum(1 for m in messages
                     for b in (m.get("content") if isinstance(m.get("content"), list) else [])
                     if isinstance(b, dict) and b.get("type") == "tool_result")
    print(f"\033[90m[HOOK] Stop：本次会话使用了 {tool_count} 次工具调用\033[0m")
    return None


register_hook("UserPromptSubmit", context_inject_hook)
register_hook("PreToolUse", permission_hook)
register_hook("PreToolUse", log_hook)
register_hook("PostToolUse", large_output_hook)
register_hook("Stop", summary_hook)


# -- 带提醒计数器的 agent 循环 --

def agent_loop(messages: list):
    rounds_since_todo = 0
    while True:
        response = client.messages.create(
            model=MODEL, system=SYSTEM, messages=messages,
            tools=TOOLS, max_tokens=8000,
        )
        messages.append({"role": "assistant", "content": response.content})

        tool_calls = [
            block for block in response.content if block.type == "tool_use"
        ]
        if not tool_calls:
            force = trigger_hooks("Stop", messages)
            if force:
                messages.append({"role": "user", "content": force})
                continue
            return

        results = []
        used_todo = False
        for block in tool_calls:
            blocked = trigger_hooks("PreToolUse", block)
            if blocked:
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": str(blocked)})
                continue

            handler = TOOL_HANDLERS.get(block.name)
            try:
                output = handler(**block.input) if handler else f"未知：{block.name}"
            except Exception as e:
                output = f"错误：{e}"

            trigger_hooks("PostToolUse", block, output)

            if block.name == "todo_write":
                used_todo = True

            results.append({"type": "tool_result", "tool_use_id": block.id,
                            "content": str(output)})

        rounds_since_todo = 0 if used_todo else rounds_since_todo + 1
        if rounds_since_todo >= 3:
            results.append({"type": "text",
                            "text": "<reminder>更新你的 todos。</reminder>"})
            rounds_since_todo = 0

        messages.append({"role": "user", "content": results})


if __name__ == "__main__":
    print("s05: TodoWrite - 先规划再执行")
    print("输入问题，按回车发送。输入 q 退出。\n")

    history = []
    while True:
        try:
            # \001/\002 告诉 Readline 这些 ANSI 转义不占显示宽度。
            query = input("\001\033[36m\002s05 >> \001\033[0m\002")
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
        trigger_hooks("UserPromptSubmit", query)
        history.append({"role": "user", "content": query})
        agent_loop(history)
        for block in history[-1]["content"]:
            if getattr(block, "type", None) == "text":
                print(block.text)
        print()
    """
    1.重构 s05_todo_write/example/hello.py：添加类型注解、文档字符串和 main 保护入口（先列 3 步再执行）
    2.在 s05_todo_write/example/demo_pkg 下创建一个 Python 包，包含 __init__.py、utils.py 和 tests/test_utils.py
    3.审查 s05_todo_write/example 下的 Python 文件并修复任何风格问题
    """
