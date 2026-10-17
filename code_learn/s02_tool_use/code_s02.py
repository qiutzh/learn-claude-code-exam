#!/usr/bin/env python3
"""
s02_tool_use.py - 工具

s01 中的 agent 循环没有改变。本课新增了四个工具
和一个分发表：

    +----------+      +-------+      +--------------------------+
    |   用户   | ---> |  LLM  | ---> | 工具分发                  |
    |  提示词  |      |       |      | bash       -> run_bash   |
    +----------+      +---+---+      | read_file  -> run_read   |
                          ^          | write_file -> run_write  |
                          |          | edit_file  -> run_edit   |
                          +----------+ glob       -> run_glob   |
                          工具结果   +--------------------------+

  + run_read / run_write / run_edit / run_glob
  + 用 TOOL_HANDLERS 替代硬编码的 run_bash 调用
  + 用 safe_path 让文件工具保持在 workspace 内

关键洞见：循环保持不变；只有工具注册和分发在增长。
"""

import os
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
    "Windows：bash 工具通过 cmd.exe 运行；请使用 cmd.exe 语法，"
    "而不是 Unix Bash 或 PowerShell 语法，并优先使用专用文件工具进行文件操作"
    if os.name == "nt"
    else "类 Unix：bash 工具运行系统 shell"
)

SYSTEM = (
    f"你是一个在 {WORKDIR} 的编码 agent。环境：{ENVIRONMENT_PROMPT}。"
    "使用工具来解决问题。行动，而不是解释。"
)


# -- 来自 s01（未改变） --

def run_bash(command: str) -> str:
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    if any(d in command for d in dangerous):
        return "错误：已阻止危险命令"
    try:
        r = subprocess.run(command, shell=True, cwd=WORKDIR,
                           capture_output=True, text=True, errors="replace",
                           timeout=120)
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(无输出)"
    except subprocess.TimeoutExpired:
        return "错误：超时（120s）"
    except (FileNotFoundError, OSError) as e:
        return f"错误：{e}"


# -- s02 新增：四个工具 --

def safe_path(p: str) -> Path:
    path = (WORKDIR / p).resolve()
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"路径逃逸出 workspace：{p}")
    return path


def run_read(path: str, limit: int | None = None) -> str:
    try:
        lines = safe_path(path).read_text(encoding="utf-8").splitlines()
        if limit and limit < len(lines):
            lines = lines[:limit] + [f"... （还有 {len(lines) - limit} 行）"]
        return "\n".join(lines)
    except Exception as e:
        return f"错误：{e}"


def run_write(path: str, content: str) -> str:
    try:
        file_path = safe_path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        return f"已写入 {len(content)} 字节到 {path}"
    except Exception as e:
        return f"错误：{e}"


def run_edit(path: str, old_text: str, new_text: str) -> str:
    try:
        file_path = safe_path(path)
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
            shown.append("... （省略了更多匹配项；请缩小 pattern 范围）")
        return "\n".join(shown) if shown else "(无匹配)"
    except Exception as e:
        return f"错误：{e}"


# -- s02 新增：工具定义（s01 只有一个工具，s02 有五个） --

TOOLS = [
    {"name": "bash", "description": "运行一个 shell 命令。",
     "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
    {"name": "read_file", "description": "读取文件内容。",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "limit": {"type": "integer"}},
                      "required": ["path"]}},
    {"name": "write_file", "description": "将内容写入文件。",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                      "required": ["path", "content"]}},
    {"name": "edit_file", "description": "在文件中精确替换一次文本。",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_text": {"type": "string"},
                                                       "new_text": {"type": "string"}},
                      "required": ["path", "old_text", "new_text"]}},
    {"name": "glob", "description": "查找匹配 glob 模式的文件；** 可递归匹配。",
     "input_schema": {"type": "object", "properties": {"pattern": {"type": "string"}}, "required": ["pattern"]}},
]

# -- s02 新增：分发表（替代 s01 中硬编码的 run_bash 调用） --

TOOL_HANDLERS = {
    "bash": run_bash, "read_file": run_read, "write_file": run_write,
    "edit_file": run_edit, "glob": run_glob,
}


# -- agent 循环保持与 s01 相同的形状；只有分发改变了 --
# s01: output = run_bash(block.input["command"])
# s02: output = TOOL_HANDLERS[block.name](**block.input)

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
            print(f"\033[33m> {block.name}\033[0m")
            handler = TOOL_HANDLERS.get(block.name)
            output = handler(**block.input) if handler else f"未知：{block.name}"
            print(str(output)[:200])
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": output})

        messages.append({"role": "user", "content": results})


if __name__ == "__main__":
    print("s02：工具使用 - 在 s01 基础上新增四个工具")
    print("输入一个问题，按 Enter 发送。输入 q 退出。\n")

    history = []
    while True:
        try:
            # \001/\002 告诉 Readline 这些 ANSI 转义符显示宽度为零。
            query = input("\001\033[36m\002s02 >> \001\033[0m\002")
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
    1.读取 README.md 文件，并告诉我这个项目是关于什么的
    2.创建一个名为 test.py 的文件，让它打印 "hello"，然后把它读回来
    3.查找此目录中的所有 Python 文件
    4.读取 README.md 和 requirements.txt，然后创建一个摘要文件
    5.读取 README.md 和 requirements.txt，同时查看此目录中的所有 Python 文件，统计py文件数量 - 测试多工具调用
    """
