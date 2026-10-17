#!/usr/bin/env python3
"""
s06_subagent.py - 子代理

task 工具会用一个全新的消息列表运行第二个代理循环。两个循环共享工作
目录，但只有最终文本会返回到父对话中。

    父代理                          子代理
    +------------------+            +------------------+
    | messages=[...]   |            | messages=[prompt]|
    |                  |   task     |                  |
    | tool: task       | ---------> | 自己的代理循环    |
    |                  |            | 仅基础工具        |
    | tool_result      | <--------- | 最终文本          |
    +------------------+            +------------------+

子代理没有 task 工具，因此它无法再次委派任务。
"""

import os
import re
import subprocess
from pathlib import Path

try:
    import readline

    readline.parse_and_bind('set bind-tty-special-chars off')
    readline.parse_and_bind('set input-meta on')
    readline.parse_and_bind('set output-meta on')
    readline.parse_and_bind('set convert-meta off')
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

ENVIRONMENT_PROMPT = (
    "Windows：bash 工具通过 cmd.exe 运行；请使用 cmd.exe 语法，而非 Unix "
    "Bash 或 PowerShell 语法，并优先使用专用文件工具进行文件操作"
    if os.name == "nt"
    else "类 Unix：bash 工具运行系统 shell"
)
SYSTEM = (
    f"你是一个位于 {WORKDIR} 的编码代理。环境：{ENVIRONMENT_PROMPT}。"
    "使用 task 进行聚焦探索或处理自包含的子任务。"
)
SUB_SYSTEM = (
    f"你是一个位于 {WORKDIR} 的编码代理。环境：{ENVIRONMENT_PROMPT}。"
    "完成给定任务，然后返回简洁的最终答案。"
)


# -- 基础工具 --

def run_bash(command: str) -> str:
    try:
        result = subprocess.run(
            command, shell=True, cwd=WORKDIR,
            capture_output=True, text=True, errors="replace", timeout=120,
        )
        output = (result.stdout + result.stderr).strip()
        return output[:50000] if output else "（无输出）"
    except subprocess.TimeoutExpired:
        return "错误：超时（120秒）"


def run_read(path: str, limit: int | None = None) -> str:
    try:
        lines = (WORKDIR / path).resolve().read_text(encoding="utf-8").splitlines()
        if limit and limit < len(lines):
            lines = lines[:limit] + [f"... （还有 {len(lines) - limit} 行）"]
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
    import glob
    try:
        matches = sorted({
            match for match in glob.glob(
                pattern, root_dir=WORKDIR, recursive=True)
            if (WORKDIR / match).resolve().is_relative_to(WORKDIR)
        })
        shown = matches[:200]
        if len(matches) > 200:
            shown.append("... （省略更多匹配项；请缩小模式范围）")
        return "\n".join(shown) if shown else "（无匹配）"
    except Exception as e:
        return f"错误：{e}"


BASE_TOOLS = [
    {"name": "bash", "description": "运行 shell 命令。",
     "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
    {"name": "read_file", "description": "读取文件内容。",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}},
                      "required": ["path"]}},
    {"name": "write_file", "description": "将内容写入文件。",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                      "required": ["path", "content"]}},
    {"name": "edit_file", "description": "替换文件中完全匹配的文本一次。",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"},
                                                       "new_text": {"type": "string"}},
                      "required": ["path", "old_text", "new_text"]}},
    {"name": "glob", "description": "查找匹配 glob 模式的文件；** 表示递归匹配。",
     "input_schema": {"type": "object", "properties": {"pattern": {"type": "string"}}, "required": ["pattern"]}},
]

BASE_HANDLERS = {
    "bash": run_bash,
    "read_file": run_read,
    "write_file": run_write,
    "edit_file": run_edit,
    "glob": run_glob,
}

# -- 钩子 --

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
    """PreToolUse：阻止被禁止的操作，并对有风险的操作进行询问。"""
    if block.name == "bash":
        command = block.input.get("command", "")
        for pattern in DENY_LIST:
            if pattern in command:
                print(f"\n\033[31m[已阻止] '{pattern}'\033[0m")
                return "权限被拒绝（拒绝列表）"
        if contains_destructive_command(command) or any(
                keyword in command for keyword in DESTRUCTIVE
        ):
            print("\n\033[33m[权限] 可能有破坏性的命令\033[0m")
            print(f"   工具：{block.name}({block.input})")
            choice = input("   是否允许？[y/N] ").strip().lower()
            if choice not in ("y", "yes"):
                return "权限被用户拒绝"

    if block.name in ("read_file", "write_file", "edit_file"):
        path = block.input.get("path", "")
        if not (WORKDIR / path).resolve().is_relative_to(WORKDIR):
            print("\n\033[33m[权限] 访问工作区之外\033[0m")
            print(f"   工具：{block.name}({block.input})")
            choice = input("   是否允许？[y/N] ").strip().lower()
            if choice not in ("y", "yes"):
                return "权限被用户拒绝"
    return None


def log_hook(block):
    """PreToolUse：记录每一次工具调用。"""
    args_preview = str(list(block.input.values())[:2])[:60]
    print(f"\033[90m[钩子] {block.name}({args_preview})\033[0m")
    return None


def large_output_hook(block, output):
    """PostToolUse：对过大的输出发出警告。"""
    if len(str(output)) > 100000:
        print(f"\033[33m[钩子] {block.name} 输出过大：{len(str(output))} 字符\033[0m")
    return None


def context_inject_hook(query: str):
    """UserPromptSubmit：记录工作目录。"""
    print(f"\033[90m[钩子] UserPromptSubmit：正在 {WORKDIR} 中工作\033[0m")
    return None


def summary_hook(messages: list):
    """Stop：打印此消息列表中工具结果的数量。"""
    tool_count = sum(
        1
        for message in messages
        for block in (
            message.get("content")
            if isinstance(message.get("content"), list)
            else []
        )
        if isinstance(block, dict) and block.get("type") == "tool_result"
    )
    print(f"\033[90m[钩子] Stop：本次会话使用了 {tool_count} 次工具调用\033[0m")
    return None


register_hook("UserPromptSubmit", context_inject_hook)
register_hook("PreToolUse", permission_hook)
register_hook("PreToolUse", log_hook)
register_hook("PostToolUse", large_output_hook)
register_hook("Stop", summary_hook)


def execute_tool(block, handlers: dict) -> str:
    blocked = trigger_hooks("PreToolUse", block)
    if blocked:
        return str(blocked)

    handler = handlers.get(block.name)
    try:
        output = handler(**block.input) if handler else f"未知：{block.name}"
    except Exception as e:
        output = f"错误：{e}"

    trigger_hooks("PostToolUse", block, output)
    return str(output)


# -- s06 新增：带全新消息的嵌套代理循环 --

SUB_TOOLS = list(BASE_TOOLS)
SUB_HANDLERS = dict(BASE_HANDLERS)


def extract_text(content) -> str:
    if not isinstance(content, list):
        return str(content)
    return "\n".join(
        getattr(block, "text", "")
        for block in content
        if getattr(block, "type", None) == "text"
    )


def run_subagent(prompt: str) -> str:
    print("\n\033[35m[子代理已启动]\033[0m")
    messages = [{"role": "user", "content": prompt}]

    for _ in range(30):
        response = client.messages.create(
            model=MODEL,
            system=SUB_SYSTEM,
            messages=messages,
            tools=SUB_TOOLS,
            max_tokens=8000,
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
            print("\033[35m[子代理已完成]\033[0m")
            return extract_text(response.content) or "（无摘要）"

        results = []
        for block in tool_calls:
            output = execute_tool(block, SUB_HANDLERS)
            print(f"  \033[90m[子] {block.name}：{output[:100]}\033[0m")
            results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": output,
            })
        messages.append({"role": "user", "content": results})

    print("\033[35m[子代理已停止]\033[0m")
    return "子代理在 30 轮后仍未给出最终答案，已停止。"


TASK_TOOL = {
    "name": "task",
    "description": "使用全新的对话上下文运行子代理，并返回其最终文本。",
    "input_schema": {
        "type": "object",
        "properties": {"prompt": {"type": "string", "minLength": 1}},
        "required": ["prompt"],
    },
}

TOOLS = [*BASE_TOOLS, TASK_TOOL]
TOOL_HANDLERS = {**BASE_HANDLERS, "task": run_subagent}


# -- 父代理循环 --

def agent_loop(messages: list):
    while True:
        response = client.messages.create(
            model=MODEL,
            system=SYSTEM,
            messages=messages,
            tools=TOOLS,
            max_tokens=8000,
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
        for block in tool_calls:
            output = execute_tool(block, TOOL_HANDLERS)
            results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": output,
            })
        messages.append({"role": "user", "content": results})


if __name__ == "__main__":
    print("s06：子代理 - 全新消息，最终文本返回")
    print("输入问题，按回车发送。输入 q 退出。\n")

    history = []
    while True:
        try:
            # \001/\002 告诉 Readline 这些 ANSI 转义的显示宽度为零。
            query = input("\001\033[36m\002s06 >> \001\033[0m\002")
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
    1.使用子任务来查明这个项目使用的是哪种测试框架（子Agent去读文件，主Agent只收结论）
    2.委派：读取agents/目录下的所有.py文件，并总结每个文件的作用
    3.使用任务创建s06_subagent/example/string_tools.py，其中包含一个slugify(text: str)函数，然后由父Agent进行验证
    """
  