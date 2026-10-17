#!/usr/bin/env python3
"""
s03_permission.py - 权限系统

在工具执行前插入三道关卡：

    关卡 1：硬拒绝列表（rm -rf /、sudo 等）
    关卡 2：规则匹配（是否在工作区外写入？是否破坏性命令？）
    关卡 3：用户审批（暂停并等待确认）

    +----------+      +-------+      +--------------+      +---------------+
    |   用户   | ---> |  LLM  | ---> |   权限系统   | ---> |   工具分发    |
    |   提示   |      |       |      | 1. 拒绝列表  |      | 执行          |
    +----------+      +---+---+      | 2. 规则      |      +-------+-------+
                          ^          | 3. 审批      |              |
                          |          +------+-------+              |
                          |                 | 拒绝                 |
                          |                 v                      v
                          |          +-------------------------------+
                          +----------+ tool_result：拒绝或输出       |
                                     +-------------------------------+

只向 agent 循环添加一行：

    if not check_permission(block):
        continue

基于 s02（多工具）构建。用法：

    python s03_permission/code_s01.py
    需要：pip install anthropic python-dotenv + 在 .env 中设置 ANTHROPIC_API_KEY
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
    f"你是一个在 {WORKDIR} 工作的编码 agent。环境：{ENVIRONMENT_PROMPT}。"
    "所有破坏性操作都需要用户审批。"
)


# -- 来自 s02：工具实现 --

def run_bash(command: str) -> str:
    try:
        r = subprocess.run(command, shell=True, cwd=WORKDIR,
                           capture_output=True, text=True, errors="replace", timeout=120)
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(无输出)"
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
    import glob as g
    try:
        matches = sorted({
            match for match in g.glob(
                pattern, root_dir=WORKDIR, recursive=True)
            if (WORKDIR / match).resolve().is_relative_to(WORKDIR)
        })
        shown = matches[:200]
        if len(matches) > 200:
            shown.append("... （更多匹配已省略；请缩小模式范围）")
        return "\n".join(shown) if shown else "(无匹配)"
    except Exception as e:
        return f"错误：{e}"


# -- 来自 s02（未更改）：工具定义和分发 --

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
]

TOOL_HANDLERS = {
    "bash": run_bash, "read_file": run_read, "write_file": run_write,
    "edit_file": run_edit, "glob": run_glob,
}

# -- s03 新增：三道关卡权限流水线 --

# 关卡 1：硬拒绝列表 - 始终禁止
DENY_LIST = ["rm -rf /", "sudo", "shutdown", "reboot", "mkfs", "dd if=", "> /dev/sda"]


def check_deny_list(command: str) -> str | None:
    for pattern in DENY_LIST:
        if pattern in command:
            return f"已阻止：'{pattern}' 在拒绝列表中"
    return None


# 关卡 2：规则匹配 - 上下文相关检查
DESTRUCTIVE_COMMAND_WORD = re.compile(
    r"(?i)(?:^|[;&|()\n])\s*(?:rm|del)(?=\s|$|[;&|()])"
)


def contains_destructive_command(command: str) -> bool:
    return bool(DESTRUCTIVE_COMMAND_WORD.search(command))


PERMISSION_RULES = [
    {"tools": ["read_file", "write_file", "edit_file"],
     "check": lambda args: not (WORKDIR / args.get("path", "")).resolve().is_relative_to(WORKDIR),
     "message": "在工作区外写入"},
    {"tools": ["bash"],
     "check": lambda args: contains_destructive_command(args.get("command", "")) or
                           any(kw in args.get("command", "") for kw in ["rm ", "> /etc/", "chmod 777"]),
     "message": "潜在破坏性命令"},
]


def check_rules(tool_name: str, args: dict) -> str | None:
    for rule in PERMISSION_RULES:
        if tool_name in rule["tools"] and rule["check"](args):
            return rule["message"]
    return None


# 关卡 3：用户审批 - 规则匹配后等待确认
def ask_user(tool_name: str, args: dict, reason: str) -> str:
    print(f"\n\033[33m[权限] {reason}\033[0m")
    print(f"   工具：{tool_name}({args})")
    choice = input("   允许？[y/N] ").strip().lower()
    return "allow" if choice in ("y", "yes") else "deny"


# 流水线：三道关卡串联
def check_permission(block) -> bool:
    if block.name == "bash":
        reason = check_deny_list(block.input.get("command", ""))
        if reason:
            print(f"\n\033[31m[已阻止] {reason}\033[0m")
            return False
    reason = check_rules(block.name, block.input)
    if reason:
        decision = ask_user(block.name, block.input, reason)
        if decision == "deny":
            return False
    return True


# -- Agent 循环：与 s02 相同，插入了 check_permission() --

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
            return

        results = []
        for block in tool_calls:
            print(f"\033[36m> {block.name}\033[0m")

            # s03 变更：在执行前经过权限流水线
            if not check_permission(block):
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": "权限被拒绝。"})
                continue

            handler = TOOL_HANDLERS.get(block.name)
            output = handler(**block.input) if handler else f"未知：{block.name}"
            print(str(output)[:200])
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": output})

        messages.append({"role": "user", "content": results})


if __name__ == "__main__":
    print("s03：权限")
    print("输入问题，按 Enter 发送。输入 q 退出。\n")

    history = []
    while True:
        try:
            # \001/\002 告诉 Readline 这些 ANSI 转义的显示宽度为零。
            query = input("\001\033[36m\002s03 >> \001\033[0m\002")
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
        history.append({"role": "user", "content": query})
        agent_loop(history)
        for block in history[-1]["content"]:
            if getattr(block, "type", None) == "text":
                print(block.text)
        print()
    """
    1.在当前目录下创建一个名为 test.txt 的文件（应该直接通过）
    2.删除文件 test.txt（bash + rm 会触发闸门 2）
    3.当前目录下有哪些文件？（只读，全部通过）
    4.尝试将文件写入 /etc/something（写工作区外，触发闸门 2）
    5.在 Windows 上，`del test.txt` 和 `DEL test.txt` 会触发闸门 2，而 `model`、`delimiter` 和 `echo del test.txt` 不会。
    """
