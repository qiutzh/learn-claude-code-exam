#!/usr/bin/env python3
"""
s01_agent_loop.py - 智能体循环

AI 编程智能体的全部秘密都在这一个模式中：

    while True:
        response = LLM(messages, tools)
        if response 中不包含 tool_use:
            break
        执行工具
        追加结果

    +----------+      +-------+      +---------+
    |   用户   | ---> |  LLM  | ---> |  工具   |
    |  提示词  |      |       |      |  执行   |
    +----------+      +---+---+      +----+----+
                          ^               |
                          |   tool_result |
                          +---------------+
                          （循环继续）

这就是核心循环：把工具结果反馈给模型，
直到模型决定停止。后续章节会在此基础上加入
策略、钩子和生命周期控制。

用法：
    pip install anthropic python-dotenv
    ANTHROPIC_API_KEY=... python s01_agent_loop/code_s01.py
"""

import os
import subprocess

try:
    import readline

    # #143 针对 macOS libedit 的 UTF-8 退格修复
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

client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))
MODEL = os.environ["MODEL_ID"]

ENVIRONMENT_PROMPT = (
    "Windows：bash 工具通过 cmd.exe 运行；请使用 cmd.exe 语法，"
    "而不是 Unix Bash 或 PowerShell 语法"
    if os.name == "nt"
    else "类 Unix：bash 工具运行系统 shell"
)
SYSTEM = (
    f"你是一个位于 {os.getcwd()} 的编程智能体。环境：{ENVIRONMENT_PROMPT}。"
    "使用 bash 来完成任务。要行动，不要解释。"
)

# -- 工具定义：仅 bash --
TOOLS = [{
    "name": "bash",
    "description": "运行一条 shell 命令。",
    "input_schema": {
        "type": "object",
        "properties": {"command": {"type": "string"}},
        "required": ["command"],
    },
}]


# -- 工具执行 --
def run_bash(command: str) -> str:
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    if any(d in command for d in dangerous):
        return "错误：已阻止危险命令"
    try:
        r = subprocess.run(command, shell=True, cwd=os.getcwd(),
                           capture_output=True, text=True, errors="replace", timeout=120)
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(无输出)"
    except subprocess.TimeoutExpired:
        return "错误：超时（120秒）"
    except (FileNotFoundError, OSError) as e:
        return f"错误：{e}"


# -- 核心模式：一个 while 循环，调用工具直到模型停止 --
def agent_loop(messages: list):
    while True:
        response = client.messages.create(
            model=MODEL, system=SYSTEM, messages=messages,
            tools=TOOLS, max_tokens=8000,
        )

        # 追加助手回合
        messages.append({"role": "assistant", "content": response.content})

        # 如果模型没有调用工具，我们就完成了
        tool_calls = [
            block for block in response.content if block.type == "tool_use"
        ]  # block.type: 只有 'thinking', 'text', 说明上一轮 loop 已经调完工具得到执行结果, 接下来退出循环
        if not tool_calls:
            return

        # 执行每个工具调用，收集结果
        results = []
        for block in tool_calls:
            print(f"\033[33m$ {block.input['command']}\033[0m")
            output = run_bash(block.input["command"])
            print(output[:200])
            results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": output,
            })

        # 把工具结果反馈回去，循环继续
        messages.append({"role": "user", "content": results})


# -- 入口点 --
if __name__ == "__main__":
    print("s01：智能体循环")
    print("输入一个问题，按回车发送。输入 q 退出。\n")

    history = []
    while True:
        try:
            # \001/\002 告诉 Readline 这些 ANSI 转义序列的显示宽度为零。
            query = input("\001\033[36m\002s01 >> \001\033[0m\002")
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
        history.append({"role": "user", "content": query})
        agent_loop(history)
        # 打印模型最终的文本回复
        response_content = history[-1]["content"]
        if isinstance(response_content, list):
            for block in response_content:
                if getattr(block, "type", None) == "text":
                    print(block.text)
        print()
    """
    1.`创建一个文件 hello.py 并打印 "Hello, World!"`
    2.`列出此目录下的所有 Python 文件`
    3.`当前 git 分支是什么？`
    """
