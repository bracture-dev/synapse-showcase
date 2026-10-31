"""Optional installer callbacks over inherited pipes, separate from the public MCP transport."""

import asyncio
import contextlib
import json
import sys
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

CAPABILITIES = ("appPlan", "appInstall", "appStatus", "appLifecycle", "agentSetup")
# The installer answers each method within its own deadline, and an expired call
# gets an explicit "outcome unknown" reply. Ours waits a little longer, so that
# reply arrives first and this timeout only covers a silent installer.
DEADLINES = {
    "hello": 10.0,
    "snapshot": 30.0,
    "appPlan": 30.0,
    "appInstall": 30.0,
    "agentSetup": 30.0,
    "appStatus": 90.0,
    "appLifecycle": 150.0,
}
DEADLINE_MARGIN = 5.0
METHODS = frozenset(DEADLINES)
MUTATIONS = frozenset(("appInstall", "appLifecycle"))
MAX_LINE = 256 * 1024
MAX_PENDING = 16


class Host(Protocol):
    capabilities: dict[str, bool]

    async def call(self, method: str, params: dict[str, Any]) -> dict[str, Any]: ...

    def subscribe(self, listener: Callable[[], None]) -> Callable[[], None]: ...


def unavailable(method: str, reason: str) -> RuntimeError:
    if method in MUTATIONS:
        return RuntimeError(
            f"{reason} The action's outcome is unknown. Read app_job_status or app_status "
            "before deciding whether to try again."
        )
    return RuntimeError(reason)


class _Output(asyncio.Protocol):
    """Honor pipe backpressure without a blocked thread preventing child shutdown."""

    def __init__(self):
        self.writable = asyncio.Event()
        self.writable.set()
        self.lost = False

    def pause_writing(self) -> None:
        self.writable.clear()

    def resume_writing(self) -> None:
        self.writable.set()

    def connection_lost(self, exc: Exception | None) -> None:
        self.lost = True
        self.writable.set()

    async def drain(self) -> None:
        await self.writable.wait()
        if self.lost:
            raise BrokenPipeError("Installer output pipe closed.")


class StdioHost:
    """One bounded JSONL channel. Only the parent process owns the other pipe ends.

    This is enabled only beside HTTP MCP. Standalone MCP keeps stdin/stdout to itself.
    Requests never retry: a lost installation reply does not establish whether it ran.
    """

    def __init__(self, reader: asyncio.StreamReader, send: Callable[[bytes], Awaitable[None]]):
        self.capabilities = dict.fromkeys(CAPABILITIES, False)
        self._reader = reader
        self._send = send
        self._pending: dict[int, tuple[asyncio.Future, str]] = {}
        self._next_id = 0
        self._listeners: set[Callable[[], None]] = set()
        self._closed = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._transports: list[Any] = []

    @classmethod
    async def connect(cls) -> "StdioHost":
        loop = asyncio.get_running_loop()
        reader = asyncio.StreamReader(limit=MAX_LINE)
        incoming, _ = await loop.connect_read_pipe(
            lambda: asyncio.StreamReaderProtocol(reader), sys.stdin.buffer
        )
        try:
            outgoing, flow = await loop.connect_write_pipe(_Output, sys.stdout.buffer)
        except BaseException:
            incoming.close()
            raise

        async def send(line: bytes) -> None:
            await flow.drain()
            outgoing.write(line)
            await flow.drain()

        host = cls(reader, send)
        host._transports = [incoming, outgoing]
        try:
            await host.start()
        except BaseException:
            await host.close()
            raise
        return host

    async def start(self) -> None:
        if self._task is not None:
            raise RuntimeError("Installer channel already started.")
        self._task = asyncio.create_task(self._receive())
        hello = await self.call("hello", {})
        caps = hello.get("capabilities")
        if (
            type(hello.get("version")) is not int
            or hello["version"] != 1
            or not isinstance(caps, dict)
            or set(caps) != set(CAPABILITIES)
            or any(type(value) is not bool for value in caps.values())
        ):
            self._finish("Unsupported Showcase host adapter handshake.")
            raise RuntimeError("Unsupported Showcase host adapter handshake.")
        self.capabilities = caps.copy()

    async def call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method not in METHODS:
            raise ValueError("Unknown Showcase host operation.")
        if self._closed.is_set():
            raise RuntimeError("Installer channel is closed; no action was sent.")
        if len(self._pending) >= MAX_PENDING:
            raise RuntimeError("Installer is busy; no action was sent.")
        self._next_id += 1
        request_id = self._next_id
        line = (
            json.dumps(
                {"id": request_id, "method": method, "params": params},
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
        if len(line) > MAX_LINE:
            raise ValueError("Installer request is too large; no action was sent.")
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = (future, method)
        try:
            async with asyncio.timeout(DEADLINES[method] + DEADLINE_MARGIN):
                await self._send(line)
                return await future
        except TimeoutError:
            raise unavailable(method, "Installer response timed out.") from None
        except (BrokenPipeError, ConnectionError):
            self._finish("Installer channel closed.")
            # Retrieve the pending exception even if the send failed before awaiting it.
            if future.done() and not future.cancelled():
                future.exception()
            raise unavailable(method, "Installer channel closed.") from None
        finally:
            self._pending.pop(request_id, None)

    def subscribe(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.add(listener)
        return lambda: self._listeners.discard(listener)

    async def wait_closed(self) -> None:
        await self._closed.wait()

    def _finish(self, message: str) -> None:
        self._closed.set()
        for future, method in self._pending.values():
            if not future.done():
                future.set_exception(unavailable(method, message))

    async def close(self) -> None:
        self._finish("Installer channel closed.")
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        for transport in self._transports:
            transport.close()
        self._listeners.clear()

    async def _receive(self) -> None:
        try:
            while True:
                line = await self._reader.readline()
                if not line:
                    self._finish("Installer channel closed.")
                    return
                if len(line) > MAX_LINE or not line.endswith(b"\n"):
                    raise ValueError("Invalid installer message length.")
                message = json.loads(line)
                if message == {"event": "changed"}:
                    for listener in tuple(self._listeners):
                        listener()
                    continue
                if not isinstance(message, dict):
                    raise ValueError("Invalid installer response.")
                request_id = message.get("id")
                if (
                    type(request_id) is not int
                    or not 0 < request_id <= self._next_id
                    or set(message) not in ({"id", "result"}, {"id", "error"})
                    or ("error" in message and not isinstance(message["error"], str))
                    or ("result" in message and not isinstance(message["result"], dict))
                ):
                    raise ValueError("Invalid installer response.")
                pending = self._pending.get(request_id)
                # A valid reply can arrive after its caller's deadline. Never repeat the action.
                if pending is None or pending[0].done():
                    continue
                future, _ = pending
                if "error" in message:
                    future.set_exception(RuntimeError(message["error"]))
                else:
                    future.set_result(message["result"])
        except (ValueError, UnicodeError, OSError, RecursionError):
            self._finish("Installer channel sent an invalid response.")
