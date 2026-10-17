#!/usr/bin/env python3
"""
s04_hooks.py - 钩子系统

钩子在智能体循环的固定节点上运行回调函数：

    用户输入
         |
         v
    UserPromptSubmit
         |
         v
    +----------+      +-------+      +------------+      +-------+
    | messages | ---> |  LLM  | ---> | PreToolUse | ---> | Tool  |
    +----------+      +---+---+      | 权限检查    |      +---+---+
         ^                | 停止      | 日志记录    |          |
         |                v          +------------+          v
         |            Stop 钩子                        PostToolUse
         |                                               |
         +---------------- tool_result ------------------+
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
    "Windows：bash 工具通过 cmd.exe 运行；请使用 cmd.exe 语法，而不是 Unix "
    "Bash 或 PowerShell 语法，并优先使用专用文件工具进行文件操作"
    if os.name == "nt"
    else "类 Unix：bash 工具运行系统 shell"
)
SYSTEM = (
    f"你是一个在 {WORKDIR} 工作的编码智能体。环境：{ENVIRONMENT_PROMPT}。 "
    "使用工具来完成任务。要行动，不要解释。"
)


# -- 来自 s02-s03：工具实现 --

def run_bash(command: str) -> str:
    try:
        r = subprocess.run(command, shell=True, cwd=WORKDIR,
                           capture_output=True, text=True, errors="replace", timeout=120)
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "（无输出）"
    except subprocess.TimeoutExpired:
        return "错误：超时（120秒）"


def run_read(path: str, limit: int | None = None) -> str:
    try:
        file_path = (WORKDIR / path).resolve()
        lines = file_path.read_text(encoding="utf-8").splitlines()
        if limit and limit < len(lines):
            lines = lines[:limit] + [f"...（还有 {len(lines) - limit} 行）"]
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
            shown.append("...（省略更多匹配项；请缩小模式范围）")
        return "\n".join(shown) if shown else "（无匹配）"
    except Exception as e:
        return f"错误：{e}"


TOOLS = [
    {"name": "bash", "description": "运行 shell 命令。",
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
]

TOOL_HANDLERS = {
    "bash": run_bash, "read_file": run_read, "write_file": run_write,
    "edit_file": run_edit, "glob": run_glob,
}

# -- s04 新增：钩子系统（s03 的权限逻辑现在通过钩子实现） --

HOOKS = {"UserPromptSubmit": [], "PreToolUse": [], "PostToolUse": [], "Stop": []}


def register_hook(event: str, callback):
    HOOKS[event].append(callback)


def trigger_hooks(event: str, *args):
    for callback in HOOKS[event]:
        result = callback(*args)
        if result is not None:  # 钩子返回结果会阻止本次工具调用。
            return result
    return None


# s03 的权限检查逻辑，现在封装为钩子
DENY_LIST = ["rm -rf /", "sudo", "shutdown", "reboot", "mkfs", "dd if="]
DESTRUCTIVE_COMMAND_WORD = re.compile(
    r"(?i)(?:^|[;&|()\n])\s*(?:rm|del)(?=\s|$|[;&|()])"
)
DESTRUCTIVE = ["rm ", "> /etc/", "chmod 777"]


def contains_destructive_command(command: str) -> bool:
    return bool(DESTRUCTIVE_COMMAND_WORD.search(command))


def permission_hook(block):
    """PreToolUse：s03 的 check_permission() 逻辑移到这里。"""
    if block.name == "bash":
        command = block.input.get("command", "")
        for pattern in DENY_LIST:
            if pattern in command:
                print(f"\n\033[31m[已阻止] '{pattern}'\033[0m")
                return "被拒绝列表拒绝"
        if contains_destructive_command(command) or any(
                kw in command for kw in DESTRUCTIVE
        ):
            print(f"\n\033[33m[权限] 可能具有破坏性的命令\033[0m")
            print(f"   工具：{block.name}({block.input})")
            choice = input("   允许？[y/N] ").strip().lower()
            if choice not in ("y", "yes"):
                return "用户拒绝权限"
    if block.name in ("read_file", "write_file", "edit_file"):
        path = block.input.get("path", "")
        if not (WORKDIR / path).resolve().is_relative_to(WORKDIR):
            print(f"\n\033[33m[权限] 访问工作区之外的路径\033[0m")
            print(f"   工具：{block.name}({block.input})")
            choice = input("   允许？[y/N] ").strip().lower()
            if choice not in ("y", "yes"):
                return "用户拒绝权限"
    return None


def log_hook(block):
    """PreToolUse：记录每次工具调用。"""
    args_preview = str(list(block.input.values())[:2])[:60]
    print(f"\033[90m[钩子] {block.name}({args_preview})\033[0m")
    return None


def large_output_hook(block, output):
    """PostToolUse：输出较大时给出警告。"""
    if len(str(output)) > 100000:
        print(f"\033[33m[钩子] {block.name} 输出较大：{len(str(output))} 字符\033[0m")
    return None


# UserPromptSubmit 钩子：在用户输入到达 LLM 之前记录
def context_inject_hook(query: str):
    print(f"\033[90m[钩子] UserPromptSubmit：当前工作目录为 {WORKDIR}\033[0m")
    return None


# Stop 钩子：循环即将退出时打印摘要
def summary_hook(messages: list):
    tool_count = sum(1 for m in messages
                     for b in (m.get("content") if isinstance(m.get("content"), list) else [])
                     if isinstance(b, dict) and b.get("type") == "tool_result")
    print(f"\033[90m[钩子] Stop：本次会话使用了 {tool_count} 次工具调用\033[0m")
    return None


register_hook("UserPromptSubmit", context_inject_hook)
register_hook("PreToolUse", permission_hook)
register_hook("PreToolUse", log_hook)
register_hook("PostToolUse", large_output_hook)
register_hook("Stop", summary_hook)


# -- 智能体循环：结构与 s03 相同，但没有硬编码检查 --
# s03：if not check_permission(block): ...
# s04：if trigger_hooks("PreToolUse", block): ...

def agent_loop(messages: list):
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
        for block in tool_calls:
            # s04 变更：钩子取代了硬编码的 check_permission()
            blocked = trigger_hooks("PreToolUse", block)
            if blocked:
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": str(blocked)})
                continue

            handler = TOOL_HANDLERS.get(block.name)
            output = handler(**block.input) if handler else f"未知：{block.name}"

            trigger_hooks("PostToolUse", block, output)  # s04：后置钩子

            results.append({"type": "tool_result", "tool_use_id": block.id, "content": output})

        messages.append({"role": "user", "content": results})


if __name__ == "__main__":
    print("s04：钩子系统 - 扩展逻辑通过钩子实现，循环保持简洁")
    print("输入问题，按回车发送。输入 q 退出。\n")

    history = []
    while True:
        try:
            # \001/\002 告诉 Readline ANSI 转义序列显示宽度为零。
            query = input("\001\033[36m\002s04 >> \001\033[0m\002")
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
    1.读取文件 README.md（应该直接通过，观察 hook 日志）
    2.创建一个名为 test.txt 的文件（通过后观察 PostToolUse 是否触发）
    3.删除 /tmp 中的所有临时文件（bash + rm 触发权限 hook）
    """
