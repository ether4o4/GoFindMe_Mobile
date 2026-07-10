"""In-process async job queue for subprocess work (tool runs + install/update).

Each job persists to the ``jobs`` table; live output is streamed to SSE
subscribers from an in-memory buffer. Concurrency is bounded by the worker count
(plus a per-tool sub-cap for heavy tools). Provider lookups are network
coroutines handled in ``orchestrate`` — they record job rows here for history but
do not occupy a subprocess worker.
"""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field

from . import db, tools
from .config import settings
from .util import audit, now_iso

_SENTINEL = object()
_HEAVY = {"amass": 1, "bbot": 1, "maigret": 2}


@dataclass
class _Runtime:
    output: list[str] = field(default_factory=list)
    subs: set[asyncio.Queue] = field(default_factory=set)
    task: asyncio.Task | None = None
    cancelled: bool = False
    done: bool = False
    status: str = "queued"


class JobQueue:
    def __init__(self, concurrency: int) -> None:
        self._q: asyncio.Queue[str] = asyncio.Queue()
        self._workers: list[asyncio.Task] = []
        self._runtime: dict[str, _Runtime] = {}
        self._sems: dict[str, asyncio.Semaphore] = {
            n: asyncio.Semaphore(c) for n, c in _HEAVY.items()
        }
        self._concurrency = concurrency
        self._bg: set[asyncio.Task] = set()  # strong refs so detached tasks aren't GC'd

    # --- lifecycle ---
    async def start(self) -> None:
        self._workers = [asyncio.create_task(self._worker(i)) for i in range(self._concurrency)]

    async def stop(self) -> None:
        for w in self._workers:
            w.cancel()
        for w in self._workers:
            try:
                await w
            except asyncio.CancelledError:
                pass

    # --- enqueue ---
    def _insert(self, kind: str, name: str, target: str, ttype: str, parent: str | None) -> str:
        jid = uuid.uuid4().hex
        db.execute(
            "INSERT INTO jobs (id, parent_id, kind, name, target, target_type, status, created_at) "
            "VALUES (?,?,?,?,?,?, 'queued', ?)",
            (jid, parent, kind, name, target, ttype, now_iso()),
        )
        self._runtime[jid] = _Runtime()
        return jid

    def enqueue_tool(self, spec: tools.ToolSpec, target: str, ttype: str,
                     parent: str | None = None) -> str:
        jid = self._insert("tool", spec.name, target, ttype, parent)
        self._q.put_nowait(jid)
        return jid

    def enqueue_manage(self, action: str, spec: tools.ToolSpec) -> str:
        # target column carries the action; name carries the tool.
        jid = self._insert("manage", spec.name, action, "manage", None)
        self._q.put_nowait(jid)
        return jid

    def record_provider_job(self, name: str, target: str, ttype: str, status: str,
                            output: str, parent: str | None) -> str:
        jid = uuid.uuid4().hex
        ts = now_iso()
        db.execute(
            "INSERT INTO jobs (id, parent_id, kind, name, target, target_type, status, "
            "output, created_at, started_at, finished_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (jid, parent, "provider", name, target, ttype, status, output, ts, ts, ts),
        )
        return jid

    def new_parent(self, target: str, ttype: str) -> str:
        jid = self._insert("search_all", "search-all", target, ttype, None)
        rt = self._runtime[jid]
        rt.status = "running"
        db.execute("UPDATE jobs SET status='running', started_at=? WHERE id=?",
                   (now_iso(), jid))
        return jid

    def track(self, coro) -> asyncio.Task:
        """Run a detached coroutine, keeping a strong reference until it finishes."""
        t = asyncio.create_task(coro)
        self._bg.add(t)
        t.add_done_callback(self._bg.discard)
        return t

    async def finalize_parent(self, parent: str, child_ids: list[str],
                              prov_task: asyncio.Task | None = None) -> None:
        """Mark a search_all parent terminal once its children + provider lookups
        finish, so it isn't stuck 'queued' (or resurrected as 'error' on restart)
        and any parent SSE subscriber closes."""
        terminal = {"done", "error", "timeout", "cancelled"}
        if prov_task is not None:
            try:
                await prov_task
            except Exception:
                pass
        waited = 0
        while child_ids and waited < 3700:
            ph = ",".join("?" * len(child_ids))
            rows = await db.aquery(f"SELECT status FROM jobs WHERE id IN ({ph})", child_ids)
            if rows and all(r["status"] in terminal for r in rows):
                break
            await asyncio.sleep(1)
            waited += 1
        await self._finish(parent, "done", 0, None)

    # --- worker ---
    async def _worker(self, idx: int) -> None:
        while True:
            jid = await self._q.get()
            try:
                await self._run(jid)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - defensive
                await self._finish(jid, "error", None, str(exc))
            finally:
                self._q.task_done()

    async def _run(self, jid: str) -> None:
        rt = self._runtime.get(jid) or _Runtime()
        self._runtime[jid] = rt
        if rt.cancelled:
            await self._finish(jid, "cancelled", None, "cancelled before start")
            return
        row = await db.aquery_one("SELECT kind, name, target FROM jobs WHERE id=?", (jid,))
        if not row:
            return
        kind, name, target = row["kind"], row["name"], row["target"]
        spec = tools.get_spec(name)
        if not spec:
            await self._finish(jid, "error", None, "unknown tool")
            return

        # Build the command for this kind.
        try:
            if kind == "tool":
                argv, stdin = tools.build_tool_argv(spec, target)
                env = None
                timeout = spec.timeout_s
            elif kind == "manage":
                action = target  # 'install' | 'update' | 'version'
                if action == "version":
                    argv = tools.version_argv(spec)
                    if argv is None:
                        await self._finish(jid, "error", None, "tool_not_installed")
                        return
                else:
                    argv, _cwd = tools.install_argv(spec, update=(action == "update"),
                                                    for_run=True)
                    if not tools.manager_available(spec.install_method):
                        await self._finish(jid, "error", None,
                                           f"{spec.install_method} not available on this host")
                        return
                stdin = None
                env = tools.mgmt_env()
                timeout = 900
            else:
                await self._finish(jid, "error", None, f"unrunnable kind: {kind}")
                return
        except FileNotFoundError:
            await self._finish(jid, "error", None, "tool_not_installed")
            return
        except (PermissionError, tools.ValidationError, tools.ManageError) as exc:
            await self._finish(jid, "error", None, str(exc))
            return

        await db.aexecute("UPDATE jobs SET status='running', started_at=? WHERE id=?",
                          (now_iso(), jid))
        rt.status = "running"
        # Register the task before the first cancellable await and re-check the
        # cancel flag, so a cancel arriving during the queued->running window
        # (rt.task was still None) is not lost and the subprocess is never spawned.
        rt.task = asyncio.current_task()
        if rt.cancelled:
            await self._finish(jid, "cancelled", None, "cancelled")
            return

        sem = self._sems.get(name)
        try:
            await self._publish(jid, _start_event(kind, name))
            runner = self._spawn(jid, rt, argv, timeout, stdin, env)
            if sem:
                async with sem:
                    status, rc, out = await runner
            else:
                status, rc, out = await runner
        except asyncio.CancelledError:
            await self._finish(jid, "cancelled", None, "cancelled")
            return
        await self._finish(jid, status, rc, None, out)

    async def _spawn(self, jid, rt, argv, timeout, stdin, env):
        async def on_output(text: str) -> None:
            rt.output.append(text)
            await self._publish(jid, {"type": "output", "data": text})
        return await tools.spawn_stream(argv, timeout, on_output=on_output, stdin=stdin, env=env)

    async def _finish(self, jid: str, status: str, rc: int | None,
                      error: str | None, output: str | None = None) -> None:
        rt = self._runtime.get(jid)
        if output is None and rt:
            output = "".join(rt.output)
        if rt:
            rt.done = True
            rt.status = status
        await db.aexecute(
            "UPDATE jobs SET status=?, returncode=?, error=?, output=?, finished_at=? WHERE id=?",
            (status, rc, error, output, now_iso(), jid),
        )
        if rt:
            await self._publish(jid, {"type": "status", "status": status,
                                      "returncode": rc, "error": error})
            for q in list(rt.subs):
                q.put_nowait(_SENTINEL)

    # --- pub/sub for SSE ---
    async def _publish(self, jid: str, event: dict) -> None:
        rt = self._runtime.get(jid)
        if not rt:
            return
        for q in list(rt.subs):
            q.put_nowait(event)

    async def subscribe(self, jid: str):
        """Async generator of SSE events: replays buffered output then tails.

        For a live job the subscriber queue is registered BEFORE any await and the
        buffer snapshot is taken in the same synchronous block, so no published
        event can fall between replay and tail (no lost output, no missed SENTINEL
        that would hang the stream).
        """
        rt = self._runtime.get(jid)
        if rt is None:
            # Not a live runtime job (provider job, or restored after restart):
            # replay from the DB and close.
            row = await db.aquery_one("SELECT status, output FROM jobs WHERE id=?", (jid,))
            if not row:
                yield {"type": "status", "status": "error", "error": "no such job"}
                return
            if row["output"]:
                yield {"type": "output", "data": row["output"]}
            yield {"type": "status", "status": row["status"]}
            return

        # Live job: register the subscriber and snapshot the buffer atomically
        # (no await between add and snapshot → the worker task cannot interleave).
        q: asyncio.Queue = asyncio.Queue()
        rt.subs.add(q)
        replay = "".join(rt.output)
        already_done = rt.done
        try:
            if replay:
                yield {"type": "output", "data": replay}
            if already_done:
                yield {"type": "status", "status": rt.status}
                return
            while True:
                item = await q.get()
                if item is _SENTINEL:
                    break
                yield item
        finally:
            rt.subs.discard(q)

    def cancel(self, jid: str) -> bool:
        rt = self._runtime.get(jid)
        if not rt or rt.done:
            return False
        rt.cancelled = True
        if rt.task:
            rt.task.cancel()
        return True


def _start_event(kind: str, name: str) -> dict:
    return {"type": "status", "status": "running", "kind": kind, "name": name}


# --- singleton wiring ---
_QUEUE: JobQueue | None = None


def get_queue() -> JobQueue:
    assert _QUEUE is not None, "job queue not started"
    return _QUEUE


async def start_queue() -> None:
    global _QUEUE
    _QUEUE = JobQueue(settings().max_concurrency)
    await _QUEUE.start()
    audit("info", "tool", "job queue started", workers=settings().max_concurrency)


async def stop_queue() -> None:
    if _QUEUE:
        await _QUEUE.stop()


# --- read helpers ---
def job_dict(jid: str) -> dict | None:
    row = db.query_one("SELECT * FROM jobs WHERE id=?", (jid,))
    if not row:
        return None
    d = dict(row)
    rt = _QUEUE._runtime.get(jid) if _QUEUE else None  # type: ignore[union-attr]
    if rt and not rt.done and rt.output:
        d["output"] = "".join(rt.output)
    return d


def list_jobs(parent: str | None = None, status: str | None = None, limit: int = 100) -> list[dict]:
    sql = ("SELECT id, parent_id, kind, name, target, target_type, status, returncode, "
           "created_at, started_at, finished_at FROM jobs")
    where, params = [], []
    if parent is not None:
        where.append("parent_id=?")
        params.append(parent)
    if status:
        where.append("status=?")
        params.append(status)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    return [dict(r) for r in db.query(sql, params)]
