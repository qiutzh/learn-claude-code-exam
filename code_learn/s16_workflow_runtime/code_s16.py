#!/usr/bin/env python3
"""
s16: 工作流运行时 - 通过一次工具调用运行已保存的编排流程。

运行：
  python s16_workflow_runtime/code_s01.py
  python s16_workflow_runtime/code_s01.py demo
  python s16_workflow_runtime/code_s01.py resume

    +-------------+       +--------------------------------+
    | 智能体循环  | ----> | Workflow(name, args, run_id)  |
    +-------------+       +---------------+----------------+
                                          |
                           +--------------+--------------+
                           | agent | parallel | pipeline  |
                           +--------------+--------------+
                                          |
                                   日志 + 结果
"""

import asyncio
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import secrets
import sys
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

WORKFLOW_AGENT_ENVIRONMENT = (
    "主机操作系统：Windows。此工作流智能体只响应其被指定的步骤；"
    "它没有直接的 shell 或文件工具。"
    if os.name == "nt"
    else "主机操作系统：类 Unix。此工作流智能体只响应其被指定的步骤；"
         "它没有直接的 shell 或文件工具。"
)

# -- 运行时保护 --
AGENT_CAP = 1000  # 每次运行中 agent() 调用的硬性上限
CONCURRENCY = 8  # 并行上限（信号量）
STORE = Path(__file__).parent / ".runtime"  # 快照与日志存放于此
MISS = object()  # 日志缓存未命中哨兵
WORKFLOW_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
RUN_ID_RE = re.compile(r"^wf_[A-Za-z0-9][A-Za-z0-9._-]{0,63}_[0-9a-f]{16}$")


def _stable_hash(s: str) -> int:
    """进程内稳定的哈希（Python 的 hash() 会因进程加盐，导致
    跨 `run` 与 `resume` 的恢复键不一致）。"""
    return int(hashlib.sha256(s.encode()).hexdigest(), 16)


def create_run_id(meta) -> str:
    return f"wf_{meta['name']}_{secrets.token_hex(8)}"


def reserve_run_id(meta) -> str:
    """在任何日志可能被截断之前，先预留一个全新的运行标识。"""
    STORE.mkdir(parents=True, exist_ok=True)
    for _ in range(32):
        run_id = validate_run_id(create_run_id(meta))
        snapshot_path = STORE / f"{run_id}.json"
        try:
            fd = os.open(snapshot_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            continue
        os.close(fd)
        return run_id
    raise WorkflowInputError("无法分配唯一的工作流 runId")


def create_task_id(run_id) -> str:
    return f"local_workflow_{run_id}"


def validate_run_id(run_id):
    if not isinstance(run_id, str) or not RUN_ID_RE.fullmatch(run_id):
        raise WorkflowInputError("无效的工作流 runId")
    return run_id


# -- 错误 --
class WorkflowInputError(Exception):
    """工作流、元数据或 schema 输入有误。"""


_run_locks_guard = threading.Lock()
_run_locks: dict[str, threading.Lock] = {}


@contextmanager
def workflow_run_lock(run_id: str):
    """在整个生命周期内，跨线程与宿主进程持有同一个运行锁。"""
    with _run_locks_guard:
        local_lock = _run_locks.setdefault(run_id, threading.Lock())
    if not local_lock.acquire(blocking=False):
        raise WorkflowInputError(f"工作流运行 {run_id} 已处于活动状态")

    handle = None
    try:
        STORE.mkdir(parents=True, exist_ok=True)
        handle = (STORE / f"{run_id}.lock").open("a+", encoding="utf-8")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise WorkflowInputError(
                f"工作流运行 {run_id} 已处于活动状态"
            ) from exc
        yield
    finally:
        if handle is not None:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()
        local_lock.release()
        with _run_locks_guard:
            if not local_lock.locked() and _run_locks.get(run_id) is local_lock:
                _run_locks.pop(run_id, None)


# -- 元数据校验 --
def validate_meta(meta):
    """在启动前校验 name、description 以及可选的 phases。"""
    if not isinstance(meta, dict):
        raise WorkflowInputError("meta 必须是对象字面量")
    if not meta.get("name") or not meta.get("description"):
        raise WorkflowInputError("meta 需要 `name` 和 `description`")
    if not isinstance(meta["name"], str) or not WORKFLOW_NAME_RE.fullmatch(meta["name"]):
        raise WorkflowInputError(
            "meta.name 必须是 1-64 个字符的 slug，只能使用字母、数字、'.'、'_' 或 '-'"
        )
    if not isinstance(meta["description"], str):
        raise WorkflowInputError("meta.description 必须是字符串")
    if "phases" in meta:
        if not isinstance(meta["phases"], list) or not all(
                isinstance(phase, str) and phase for phase in meta["phases"]
        ):
            raise WorkflowInputError("meta.phases 必须是非空字符串组成的列表")
    return meta


def check_permission(meta, settings=None):
    """在启动工作流之前应用 s03 的允许/拒绝门控。"""
    settings = settings or {}
    if meta["name"] in settings.get("deny", []):
        raise WorkflowInputError(f"工作流 '{meta['name']}' 被设置拒绝")
    return "allow"


# -- 极简 JSON Schema --
class SimpleJsonSchema:
    """支撑 agent({schema}) 的微型校验器：
    object/array/string/boolean/number + 必填键。"""

    def __init__(self, schema):
        self.schema = schema

    def validate(self, value, schema=None):
        schema = self.schema if schema is None else schema
        if "enum" in schema and value not in schema["enum"]:
            return False, f"应为 {schema['enum']} 之一"
        t = schema.get("type")
        if t == "object":
            if not isinstance(value, dict):
                return False, "应为对象"
            for key in schema.get("required", []):
                if key not in value:
                    return False, f"缺少必填键 '{key}'"
            for key, sub in schema.get("properties", {}).items():
                if key in value:
                    ok, err = self.validate(value[key], sub)
                    if not ok:
                        return False, f"{key}: {err}"
            return True, None
        if t == "array":
            if not isinstance(value, list):
                return False, "应为数组"
            items = schema.get("items")
            if items:
                for i, el in enumerate(value):
                    ok, err = self.validate(el, items)
                    if not ok:
                        return False, f"[{i}]: {err}"
            return True, None
        if t == "string":
            return (isinstance(value, str), None if isinstance(value, str) else "应为字符串")
        if t == "boolean":
            return (isinstance(value, bool), None if isinstance(value, bool) else "应为布尔值")
        if t in ("number", "integer"):
            ok = isinstance(value, (int, float)) and not isinstance(value, bool)
            return (ok, None if ok else "应为数字")
        return True, None


def _fill_schema(schema, seed):
    """mock 未特判的 schema 所使用的确定性通用填充器。"""
    t = schema.get("type")
    if t == "object":
        keys = schema.get("required") or list(schema.get("properties", {}))
        return {k: _fill_schema(schema["properties"][k], f"{seed}/{k}") for k in keys}
    if t == "array":
        return [_fill_schema(schema["items"], f"{seed}/0")]
    if t == "boolean":
        return _stable_hash(seed) % 4 != 0
    if t in ("number", "integer"):
        return _stable_hash(seed) % 5
    return seed.rsplit("/", 1)[-1]


# -- 智能体运行器 --


@dataclass(frozen=True)
class RunnerOutput:
    value: object
    tokens: int


class MockAgentRunner:
    """demo 模式与单元测试使用的确定性运行器。"""

    def run(self, prompt, schema=None, label=None):
        if schema is None:
            value = f"[mock] {(label or prompt)[:60]}"
            return RunnerOutput(value, self._tokens(prompt, value))
        props = schema.get("properties", {})
        if "findings" in props:
            n = 1 + (_stable_hash(prompt) % 2)
            sev = ["high", "medium", "low"]
            value = {"findings": [
                {"title": f"{label or 'audit'} #{i + 1}",
                 "severity": sev[_stable_hash(prompt + str(i)) % 3]}
                for i in range(n)
            ]}
        elif "isReal" in props:
            real = _stable_hash(prompt) % 4 != 0
            value = {"isReal": real,
                     "reason": "复现成功" if real else "无法复现"}
        else:
            value = _fill_schema(schema, prompt)
        return RunnerOutput(value, self._tokens(prompt, value))

    @staticmethod
    def _tokens(prompt, result):
        return len(prompt) // 4 + len(json.dumps(result, default=str)) // 4


def _response_text(response) -> str:
    return "\n".join(
        str(getattr(block, "text", ""))
        for block in getattr(response, "content", [])
        if getattr(block, "type", None) == "text"
    ).strip()


def _parse_runner_json(text: str) -> object:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        lines = lines[1:] if lines else lines
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        for position, character in enumerate(stripped):
            if character != "{":
                continue
            try:
                value, _ = decoder.raw_decode(stripped[position:])
            except json.JSONDecodeError:
                continue
            return value
        raise WorkflowInputError("工作流智能体返回了无效的 JSON")


class AnthropicAgentRunner:
    """通过与宿主相同的 API 客户端运行工作流智能体。"""

    def __init__(self, client, model):
        self.client = client
        self.model = model

    def run(self, prompt, schema=None, label=None):
        request = prompt
        if schema is not None:
            request += (
                    "\n\n只返回一个符合此 schema 的 JSON 对象：\n"
                    + json.dumps(schema, ensure_ascii=True, sort_keys=True)
            )
        response = self.client.messages.create(
            model=self.model,
            system=(
                    "你是一个专注的工作流智能体。只完成被指定的步骤。"
                    + f"{WORKFLOW_AGENT_ENVIRONMENT} "
                    + "不要声称拥有提示中未包含的文件或结果的访问权限。"
            ),
            messages=[{"role": "user", "content": request}],
            max_tokens=2000,
        )
        text = _response_text(response)
        if schema is None:
            value = text
        else:
            try:
                value = _parse_runner_json(text)
            except WorkflowInputError:
                # 让 ExecutionState 的 schema 校验触发其单次重试。
                value = text
        usage = getattr(response, "usage", None)
        tokens = int(getattr(usage, "input_tokens", 0) or 0) + int(
            getattr(usage, "output_tokens", 0) or 0
        )
        return RunnerOutput(value, tokens)


RUNNER_FACTORY = MockAgentRunner


# -- 日志 --
class WorkflowJournal:
    """仅追加的 <runId>.journal.jsonl。恢复时，语义键已存在的 agent()
    调用会从缓存重放，而不是重新运行。"""

    def __init__(self, run_id, resume, store=None):
        store = STORE if store is None else store
        store.mkdir(parents=True, exist_ok=True)
        self.path = store / f"{run_id}.journal.jsonl"
        self.resume = resume
        self.cache = {}
        if resume:
            if not self.path.exists():
                raise WorkflowInputError(f"未找到 {run_id} 的恢复日志")
            for line_number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), start=1):
                try:
                    rec = json.loads(line)
                    if (
                            not isinstance(rec, dict)
                            or not isinstance(rec.get("key"), str)
                            or "value" not in rec
                    ):
                        raise ValueError("应为键/值记录")
                except (json.JSONDecodeError, ValueError) as exc:
                    raise WorkflowInputError(
                        f"第 {line_number} 行的恢复日志记录无效"
                    ) from exc
                self.cache[rec["key"]] = rec["value"]
            self._f = self.path.open("a", encoding="utf-8")
        else:
            self._f = self.path.open("w", encoding="utf-8")  # 全新运行会截断

    def key(self, kind, label, prompt, schema):
        # 确定性的语义键，与并发顺序无关，这样并行/流水线调用在恢复时
        # 会得到相同的键。
        basis = f"{kind}|{label}|{prompt}|{json.dumps(schema, sort_keys=True)}"
        return f"{kind}-{_stable_hash(basis) % 10 ** 10:010d}"

    def cached(self, key):
        return self.cache.get(key, MISS)

    def record(self, key, value):
        self._f.write(json.dumps({"key": key, "value": value}) + "\n")
        self._f.flush()
        self.cache[key] = value

    def close(self):
        self._f.close()


# -- Token 预算 --
class Budget:
    """budget.total / spent() / remaining()。一旦花费达到总量，agent()
    调用会抛出异常，而不是静默超支。"""

    def __init__(self, total=None):
        self.total = total
        self._spent = 0

    def add(self, n):
        if self.total is not None and self._spent + n > self.total:
            raise WorkflowInputError(
                f"token 预算超支（{self._spent + n} > {self.total}）"
            )
        self._spent += n

    def spent(self):
        return self._spent

    def remaining(self):
        return float("inf") if self.total is None else max(0, self.total - self._spent)


# -- 工作流任务生命周期 --
class LocalWorkflowTask:
    """持有工作流状态、用量与进度事件。"""

    def __init__(self, task_id, run_id, meta):
        self.task_id = task_id
        self.run_id = run_id
        self.meta = meta
        self.status = "running"
        self.usage = {"agents": 0, "tokens": 0}
        self.progress = []

    def event(self, name, **data):
        line = " ".join(f"{k}={v}" for k, v in data.items())
        print(f"  事件       {name:<18} {line}")

    def progress_event(self, ptype, **data):
        self.progress.append({"type": ptype, **data})
        line = " ".join(f"{k}={v}" for k, v in data.items())
        print(f"  进度       {ptype:<16} {line}")


# -- 工作流原语 --
class ExecutionLimits:
    """共享的运行级限制，包括嵌套工作流。"""

    def __init__(self):
        self.agents = 0
        self.semaphore = asyncio.Semaphore(CONCURRENCY)

    def claim_agent(self):
        self.agents += 1
        if self.agents > AGENT_CAP:
            raise WorkflowInputError(f"已达到 agent() 上限（{AGENT_CAP}）")


class ExecutionState:
    """注入到工作流脚本中，携带编排原语。"""

    def __init__(self, task, journal, runner, budget, args, depth=0, limits=None):
        self.task = task
        self.journal = journal
        self.runner = runner
        self.budget = budget
        self.args = args
        self._depth = depth
        self._phase = None
        self._phases_seen = set()
        self._limits = limits or ExecutionLimits()

    def phase(self, title):
        """开始一个阶段；后续 agent() 会归入该阶段。幂等更新：重复发出
        同一阶段（例如来自每个流水线项）不会重复通告。"""
        self._phase = title
        if title not in self._phases_seen:
            self._phases_seen.add(title)
            self.task.progress_event("workflow_phase", title=title)

    def log(self, message):
        """发出 workflow_log 进度行。"""
        self.task.progress_event("workflow_log", message=message)

    async def agent(self, prompt, schema=None, label=None, phase=None):
        """派生一个子智能体。带 schema 时，强制 StructuredOutput + 校验
        （重试一次）。恢复时，命中的缓存键会短路本次运行。"""
        label = label or (prompt[:24] + "...")
        self._limits.claim_agent()
        if self.budget.remaining() <= 0:
            raise WorkflowInputError("token 预算超支")

        key = self.journal.key("agent", label, prompt, schema)
        cached = self.journal.cached(key)
        if cached is not MISS:
            if schema is not None:
                ok, err = SimpleJsonSchema(schema).validate(cached)
                if not ok:
                    raise WorkflowInputError(
                        f"缓存的智能体输出未通过 schema 校验：{err}"
                    )
            self.task.progress_event("workflow_agent", label=label,
                                     phase=phase or self._phase, status="cached")
            return cached

        async with self._limits.semaphore:
            run = await asyncio.to_thread(
                self.runner.run, prompt, schema, label
            )
            result = run.value
            tokens = run.tokens

        if schema is not None:
            ok, err = SimpleJsonSchema(schema).validate(result)
            if not ok:
                retry = await asyncio.to_thread(
                    self.runner.run,
                    prompt + "\n\n请返回有效的 JSON。",
                    schema,
                    label,
                )
                result = retry.value
                tokens += retry.tokens
                ok, err = SimpleJsonSchema(schema).validate(result)
                if not ok:
                    raise WorkflowInputError(f"agent({{schema}}) 输出无效：{err}")

        self.budget.add(tokens)
        self.task.usage["agents"] += 1
        self.task.usage["tokens"] += tokens
        self.journal.record(key, result)
        self.task.progress_event("workflow_agent", label=label,
                                 phase=phase or self._phase, status="done")
        return result

    async def parallel(self, thunks):
        """屏障：并发运行所有 thunk，任一 thunk 失败则整体失败。"""
        return await asyncio.gather(*[thunk() for thunk in thunks])

    async def pipeline(self, items, *stages):
        """逐项分阶段流程，阶段之间没有屏障：项 A 可以处于第 3 阶段，
        而项 B 仍在第 1 阶段。每个阶段接收
        (prev_result, original_item, index)。某阶段抛出异常会使工作流失败。"""

        async def run_item(item, idx):
            value = item
            for stage in stages:
                value = await stage(value, item, idx)
            return value

        return await asyncio.gather(*[run_item(it, i) for i, it in enumerate(items)])

    async def workflow(self, name, args=None):
        """将已保存的工作流作为子流程内联运行（仅一层），共享本次运行的
        日志 + 预算 + 智能体计数器。"""
        if self._depth >= 1:
            raise WorkflowInputError("workflow() 嵌套仅允许一层")
        if name not in WORKFLOWS:
            raise WorkflowInputError(f"未知工作流 '{name}'")
        meta, fn = WORKFLOWS[name]
        child = ExecutionState(self.task, self.journal, self.runner, self.budget,
                               args or {}, depth=self._depth + 1,
                               limits=self._limits)
        return await fn(child, args or {})


# -- 工作流工具 --
class WorkflowTool:
    """Workflow 工具。.call() 会校验 meta、执行权限检查、创建
    runId/taskId、注册 LocalWorkflowTask，并在执行脚本时发出生命周期
    事件。它返回结果与任务状态，并支持恢复。"""

    async def call(self, meta, script_fn, args=None, resume_from_run_id=None):
        validate_meta(meta)
        check_permission(meta)
        resuming = resume_from_run_id is not None
        if resuming:
            run_id = validate_run_id(resume_from_run_id)
        else:
            run_id = reserve_run_id(meta)
        with workflow_run_lock(run_id):
            return await self._call_locked(
                meta, script_fn, args, run_id, resuming
            )

    async def _call_locked(self, meta, script_fn, args, run_id, resuming):
        if resuming:
            snapshot = _read_snapshot(run_id)
            if snapshot.get("workflowName") != meta["name"]:
                raise WorkflowInputError("恢复的 runId 与工作流 meta 不匹配")
            saved_args = snapshot.get("args", {})
            if args is None:
                args = saved_args
            elif args != saved_args:
                raise WorkflowInputError("恢复参数与原始运行不匹配")
            journal = WorkflowJournal(run_id, resume=True)
        else:
            args = args or {}
            journal = WorkflowJournal(run_id, resume=False)
        task_id = create_task_id(run_id)

        task = LocalWorkflowTask(task_id, run_id, meta)
        # 在工作流执行开始前记录启动信封。
        launched = {"status": "async_launched", "taskId": task_id,
                    "taskType": "local_workflow", "runId": run_id,
                    "workflowName": meta["name"]}
        task.event("async_launched", runId=run_id, taskId=task_id)
        task.event("task_started", workflow=meta["name"],
                   phases=",".join(meta.get("phases", [])) or "-",
                   resume=resuming)
        _write_json(STORE / f"{run_id}.json", {
            "runId": run_id,
            "workflowName": meta["name"],
            "args": args,
            "task": serialize_task(task),
        })

        try:
            ctx = ExecutionState(
                task, journal, RUNNER_FACTORY(), Budget(args.get("budget")), args
            )
            result = await script_fn(ctx, args)
            task.status = "completed"
        except Exception as e:  # 失败/停止同样会关闭循环
            task.status = "failed"
            result = {"error": str(e)}
        finally:
            journal.close()

        _write_json(STORE / f"{run_id}.output.json", result)
        _write_json(STORE / f"{run_id}.json", {
            "runId": run_id,
            "workflowName": meta["name"],
            "args": args,
            "task": serialize_task(task),
        })
        _save_last_run(run_id)
        task.event("task_notification", status=task.status,
                   agents=task.usage["agents"], tokens=task.usage["tokens"],
                   outputFile=f".runtime/{run_id}.output.json")
        return {"launched": launched, "result": result, "task": task}


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, default=str), encoding="utf-8")
    os.replace(temporary, path)


def _read_snapshot(run_id):
    path = STORE / f"{run_id}.json"
    if not path.exists():
        raise WorkflowInputError(f"未找到 {run_id} 的恢复快照")
    try:
        snapshot = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise WorkflowInputError(f"{run_id} 的恢复快照无效") from exc
    if not isinstance(snapshot, dict):
        raise WorkflowInputError(f"{run_id} 的恢复快照无效")
    return snapshot


def _save_last_run(run_id):
    (STORE / "last_run.txt").write_text(run_id, encoding="utf-8")


def _read_last_run():
    p = STORE / "last_run.txt"
    return p.read_text(encoding="utf-8").strip() if p.exists() else None


# -- 示例工作流 --
FINDINGS_SCHEMA = {
    "type": "object", "required": ["findings"],
    "properties": {"findings": {"type": "array", "items": {
        "type": "object", "required": ["title", "severity"],
        "properties": {
            "title": {"type": "string"},
            "severity": {
                "type": "string", "enum": ["high", "medium", "low"]
            },
        }}}},
}
VERDICT_SCHEMA = {
    "type": "object", "required": ["isReal", "reason"],
    "properties": {"isReal": {"type": "boolean"}, "reason": {"type": "string"}},
}

SAMPLE_META = {
    "name": "review-changes",
    "description": "跨多个维度审查变更文件，并逐一验证每个发现",
    "phases": ["Review", "Verify"],
}

DIMENSIONS = ["correctness", "security", "performance", "style"]
DEMO_CHANGES = (
    "def load_user(user_id):\n"
    "    query = f\"SELECT * FROM users WHERE id = {user_id}\"\n"
    "    return db.execute(query).fetchone()\n"
)


async def sample_workflow(ctx, args):
    """对审查维度执行流水线（审查 -> 逐个验证），然后仅保留验证器
    确认的发现。计划即代码，而非一次对话轮次。"""
    ctx.phase("Review")
    changes = args.get("changes", "")
    if not isinstance(changes, str):
        raise WorkflowInputError("args.changes 必须是字符串")
    review_input = changes.strip() or "未提供变更上下文。"

    async def audit(_value, dimension, _idx):
        out = await ctx.agent(
            f"审查此变更上下文中 {dimension} 方面的问题。"
            "只报告有供文本支持的 issue。\n\n"
            f"{review_input}",
            schema=FINDINGS_SCHEMA, label=f"audit:{dimension}", phase="Review")
        return {"dimension": dimension, "findings": out["findings"]}

    async def verify(audited, dimension, _idx):
        ctx.phase("Verify")
        # 每个发现都由各自的对抗式子智能体并发验证。
        verdicts = await ctx.parallel([
            (lambda f=f: ctx.agent(
                f"针对提供的变更上下文，对抗式验证此 {dimension} 发现。\n\n"
                f"变更上下文：\n{review_input}\n\n"
                f"发现：\n{json.dumps(f, ensure_ascii=True)}",
                schema=VERDICT_SCHEMA, label=f"verify:{dimension}:{f['title']}", phase="Verify"))
            for f in audited["findings"]])
        confirmed = [f for f, v in zip(audited["findings"], verdicts)
                     if v and v.get("isReal")]
        return {"dimension": dimension, "confirmed": confirmed}

    results = await ctx.pipeline(DIMENSIONS, audit, verify)
    confirmed = [{"dimension": r["dimension"], **f}
                 for r in results if r for f in r["confirmed"]]
    confirmed.sort(key=lambda f: {"high": 0, "medium": 1, "low": 2}.get(f["severity"], 3))
    ctx.log(f"确认了 {len(confirmed)} 个真实发现")
    return {"confirmed": confirmed}


# 已保存的工作流注册表
WORKFLOWS = {SAMPLE_META["name"]: (SAMPLE_META, sample_workflow)}

WORKFLOW_TOOL = {
    "name": "Workflow",
    "description": "按名称运行已保存的工作流。在 args 中传入输入。",
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "args": {"type": "object"},
            "resume_from_run_id": {"type": "string"},
        },
        "required": ["name"],
        "additionalProperties": False,
    },
}


def serialize_task(task):
    return {
        "taskId": task.task_id,
        "taskType": "local_workflow",
        "runId": task.run_id,
        "workflowName": task.meta["name"],
        "status": task.status,
        "usage": dict(task.usage),
        "progress": list(task.progress),
    }


async def run_workflow(name, args=None, resume_from_run_id=None):
    """面向模型的适配器：从宿主注册表解析受信任的代码。"""
    if not isinstance(name, str):
        raise WorkflowInputError("工作流名称必须是字符串")
    if name not in WORKFLOWS:
        raise WorkflowInputError(f"未知工作流 '{name}'")
    if args is not None and not isinstance(args, dict):
        raise WorkflowInputError("工作流 args 必须是对象")
    meta, script_fn = WORKFLOWS[name]
    out = await WorkflowTool().call(
        meta,
        script_fn,
        args=args,
        resume_from_run_id=resume_from_run_id,
    )
    return {
        "launched": out["launched"],
        "result": out["result"],
        "task": serialize_task(out["task"]),
    }


WORKFLOW_HANDLERS = {"Workflow": run_workflow}
INHERITS_TOOLS_FROM = "s15"


def run_workflow_sync(**tool_input):
    """将同步宿主分发器桥接到异步工作流运行时。"""
    try:
        return json.dumps(asyncio.run(run_workflow(**tool_input)), default=str)
    except WorkflowInputError as exc:
        return f"错误：{exc}"


def install_workflow_tool(host):
    """扩展 s15 宿主工具池，而不改动其分发循环。"""
    global RUNNER_FACTORY
    RUNNER_FACTORY = lambda: AnthropicAgentRunner(host.client, host.MODEL)
    if getattr(host, "_workflow_tool_installed", False):
        return
    base_assemble = host.assemble_tool_pool

    def assemble_with_workflow():
        tools, handlers = base_assemble()
        if not any(tool.get("name") == "Workflow" for tool in tools):
            tools.append(WORKFLOW_TOOL)
        handlers["Workflow"] = run_workflow_sync
        return tools, handlers

    host.assemble_tool_pool = assemble_with_workflow
    host._workflow_tool_installed = True


def load_integrated_host():
    """延迟加载 s15，这样确定性的工作流测试无需 API key。"""
    path = Path(__file__).resolve().parents[1] / "s15_integrated_harness" / "code_s01.py"
    spec = importlib.util.spec_from_file_location("integrated_host", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法从 {path} 加载集成宿主")
    host = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = host
    spec.loader.exec_module(host)
    return host


# -- 命令行 --
async def run_demo(argv):
    resume_id = None
    if argv and argv[0] == "resume":
        resume_id = _read_last_run()
        if not resume_id:
            print("没有可恢复的运行；请先运行 `python code_s01.py demo`。")
            return
        print(f"正在恢复 {resume_id}；未改变的 agent() 调用将使用日志缓存\n")
    else:
        print("正在启动工作流 `review-changes`\n")

    out = await WORKFLOW_HANDLERS["Workflow"](
        name="review-changes",
        args={"budget": None, "changes": DEMO_CHANGES},
        resume_from_run_id=resume_id,
    )

    print("\n结果：")
    for f in out["result"].get("confirmed", []):
        print(f"  [{f['severity']:<6}] {f['dimension']}: {f['title']}")
    task = out["task"]
    usage = task["usage"]
    print(f"\nstatus={task['status']}  agents={usage['agents']}  "
          f"tokens={usage['tokens']}  journal=.runtime/{task['runId']}.journal.jsonl")


PROMPT = "\033[36ms16 >> \033[0m"
# \001/\002 告诉 Readline 这些 ANSI 转义符显示宽度为零。
READLINE_PROMPT = "\001\033[36m\002s16 >> \001\033[0m\002"


def run_cli():
    """运行累积的 s15 宿主，并将 Workflow 加入其工具池。"""
    host = load_integrated_host()
    install_workflow_tool(host)
    host.CONSOLE.set_prompt(PROMPT, READLINE_PROMPT)
    host.CLI_ACTIVE = True
    host.start_runtime_services()
    print("s16：工作流运行时")
    print("输入问题，按回车发送。输入 q 退出。\n")
    history = []
    context = host.update_context({}, history)
    session_state = {"active_user_request": "（当前无活动用户请求）"}
    threading.Thread(
        target=host.async_event_loop,
        args=(history, context, session_state),
        daemon=True,
    ).start()
    while True:
        try:
            query = host.CONSOLE.ask()
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
        with host.agent_lock:
            host.trigger_hooks("UserPromptSubmit", query)
            turn_start = len(history)
            session_state["active_user_request"] = query
            history.append({"role": "user", "content": query})
            host.agent_loop(history, context, query)
            context = host.update_context(context, history)
            host.print_turn_assistants(history, turn_start)
        print()


if __name__ == "__main__":
    if sys.argv[1:] and sys.argv[1] in {"demo", "resume"}:
        asyncio.run(run_demo(sys.argv[1:]))
    else:
        run_cli()
