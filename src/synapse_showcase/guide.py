"""The guide's MCP servers, the state they share and the notices that keep every view current."""

import asyncio
import contextlib
import json
import os
import weakref
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from fastmcp.resources import FileResource
from fastmcp.server.middleware import Middleware, MiddlewareContext
from fastmcp.tools import Tool, ToolResult
from jsonschema import Draft202012Validator
from jsonschema.exceptions import best_match
from mcp.types import TextContent, ToolAnnotations
from pydantic import Field

from synapse_showcase import __version__
from synapse_showcase.assets import asset_root
from synapse_showcase.content import FOCUS, STEP_IDS, STEPS
from synapse_showcase.host import CAPABILITIES, Host
from synapse_showcase.skills import Skill, SkillsExtension
from synapse_showcase.state import GuideStore

INSTRUCTIONS = (
    "An optional NimbleBrain guide. Read guide_status first. Follow the person's chosen pace; "
    "every lesson can be skipped. Buttons and agents share persistent state. guide_view affects "
    "only this guide's view; never cycle zoom. board_add/board_move change clearly labeled "
    "sample cards, separate from NimbleBrain Tasks. catalog_list describes choices; it does not "
    "install or authorize anything. External services provide their own tools and account data; "
    "their authorization belongs to the installation's supported setup. No tool handles provider "
    "keys or makes provider requests. Never change host DOM. An external connection check does "
    "not prove a provider-backed chat works."
)
APP_INSTRUCTIONS = (
    " Apps such as Todo Board and CRM have screens inside NimbleBrain. Read app_plan to review "
    "source, locked dependencies, local server, workspace connection, prerequisites and possible "
    "managed-runtime restart. The person chooses Review, then Install or Connect, in Showcase; "
    "only that click calls app_install. Installation returns a host job, which can outlast a "
    "managed-runtime restart. Poll app_job_status and report ready only after verified tools and "
    "UI. Adding an app does not authorize external accounts or expand existing external data "
    "access. Missing host prerequisites and package policy approvals belong to the operator; "
    "never change package policy or acquire provider keys."
)
GUIDE_URI = "ui://showcase/guide"
UI_META = {"ui": {"resourceUri": GUIDE_URI}}
SKILLS = (
    Skill(
        name="guide-skill",
        uri="skill://showcase/guide/SKILL.md",
        path=asset_root() / "skills" / "guide" / "SKILL.md",
        title="Guide the first few steps",
    ),
    Skill(
        name="add-app-skill",
        uri="skill://showcase/add-app/SKILL.md",
        path=asset_root() / "skills" / "add-app" / "SKILL.md",
        title="Add an available app",
    ),
)
SCHEMA = "https://json-schema.org/draft/2020-12/schema"
READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)
# Other processes write the same file, so its revision is polled. A file watcher loses the
# file once an atomic rename replaces it, and its events differ by platform.
POLL_SECONDS = 0.25

Handler = Callable[[dict[str, Any]], Awaitable[ToolResult]]


def result(data: dict[str, Any]) -> ToolResult:
    text = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    return ToolResult(content=[TextContent(type="text", text=text)], structured_content=data)


def failure(message: str) -> ToolResult:
    return ToolResult(content=[TextContent(type="text", text=message)], is_error=True)


class GuideTool(Tool):
    """A tool with a written-out schema, so an omitted argument stays distinct from null."""

    handler: Handler = Field(exclude=True)

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        # The schema allows unknown keys; no handler sees them.
        known = self.parameters["properties"]
        arguments = {key: value for key, value in arguments.items() if key in known}
        error = best_match(Draft202012Validator(self.parameters).iter_errors(arguments))
        if error is not None:
            where = ".".join(str(part) for part in error.absolute_path) or "arguments"
            return failure(
                f"Input validation error: Invalid arguments for tool {self.name}: "
                f"{where}: {error.message}"
            )
        try:
            return await self.handler(arguments)
        except Exception as error:
            # A refused change leaves the saved file as it was; say why as a tool error.
            return failure(str(error) or "The action could not finish.")


def tool(
    name: str,
    title: str,
    description: str,
    handler: Handler,
    properties: dict[str, Any] | None = None,
    required: tuple[str, ...] = (),
    annotations: ToolAnnotations = WRITE,
    meta: dict[str, Any] | None = None,
) -> GuideTool:
    schema: dict[str, Any] = {"type": "object", "$schema": SCHEMA, "properties": properties or {}}
    if required:
        schema["required"] = list(required)
    return GuideTool(
        name=name,
        title=title,
        description=description,
        parameters=schema,
        annotations=annotations,
        meta=UI_META if meta is None and annotations is WRITE else meta,
        handler=handler,
    )


class Guide:
    """One saved guide served to any number of MCP servers and sessions.

    `make_server()` builds the native tool set; `make_server(external=True)` adds the external
    agent's connection check. While any of them runs, the guide polls the saved revision and
    announces each change with `notifications/resources/list_changed` on every open session, so
    a write from any process refreshes every view.
    """

    def __init__(self, store: GuideStore, host: Host | None = None):
        self.store = store
        self.host = host
        self.listeners: set[Callable[[], None]] = set()
        self._sessions: weakref.WeakSet[Any] = weakref.WeakSet()
        self._users = 0
        self._watcher: asyncio.Task[None] | None = None
        self._last: int | None = None
        self._host_watcher: asyncio.Task[None] | None = None
        self._host_changed = asyncio.Event()
        self._unsubscribe: Callable[[], None] | None = None

    async def _read_host(self) -> dict[str, Any]:
        if self.host is None:
            return {"installation": {"managed": False}, "apps": [], "appJob": None}
        try:
            observed = await self.host.call("snapshot", {})
            if (
                not isinstance(observed.get("installation"), dict)
                or not isinstance(observed.get("apps"), list)
                or not isinstance(observed.get("appJob"), (dict, type(None)))
            ):
                raise ValueError("Invalid host snapshot.")
            return observed
        except Exception:
            return {
                "installation": {
                    "hostError": "Host status is unavailable. The guide and practice board still work."
                },
                "apps": [],
                "appJob": None,
            }

    async def snapshot(self) -> dict[str, Any]:
        observed = await self._read_host()
        catalog = self.store.catalogue()
        if observed.get("browseConnectorsUrl"):
            catalog = [
                {**item, "browseUrl": observed["browseConnectorsUrl"]}
                if item.get("action") == "browse-connectors"
                else item
                for item in catalog
            ]
        return {
            **self.store.read(),
            "steps": list(STEPS),
            "catalog": catalog,
            "installation": observed["installation"],
            "apps": observed["apps"],
            "appJob": observed.get("appJob"),
            "capabilities": {
                name: bool(self.host and self.host.capabilities[name]) for name in CAPABILITIES
            },
        }

    async def _mutate(self, edit: Callable[[], object]) -> ToolResult:
        edit()
        return result(await self.snapshot())

    def make_server(self, external: bool = False) -> FastMCP:
        instructions = INSTRUCTIONS
        if self.host is not None:
            if self.host.capabilities["appPlan"] or self.host.capabilities["appInstall"]:
                instructions += APP_INSTRUCTIONS
            if self.host.capabilities["agentSetup"]:
                instructions += " guide_agent_setup gives external-agent instructions."
        server = FastMCP(
            "showcase", instructions=instructions, version=__version__, lifespan=self._lifespan
        )
        server.add_middleware(_Sessions(self))
        for item in self._tools(external):
            server.add_tool(item)
        directory = Path(os.environ.get("SHOWCASE_UI_DIR", asset_root() / "ui" / "dist"))
        server.add_resource(
            FileResource(
                uri=GUIDE_URI,
                name="guide",
                title="Showcase",
                mime_type="text/html;profile=mcp-app",
                path=(directory / "index.html").resolve(),
                is_binary=False,
            )
        )
        SkillsExtension(SKILLS).install(server)
        return server

    def _tools(self, external: bool) -> list[GuideTool]:
        store = self.store

        async def status(_: dict[str, Any]) -> ToolResult:
            return result(await self.snapshot())

        async def step(args: dict[str, Any]) -> ToolResult:
            return await self._mutate(
                lambda: store.step(
                    args["step"], args.get("complete", False), args.get("skip", False)
                )
            )

        async def preferences(args: dict[str, Any]) -> ToolResult:
            return await self._mutate(
                lambda: store.preferences(pace=args.get("pace"), theme=args.get("theme"))
            )

        async def view(args: dict[str, Any]) -> ToolResult:
            return await self._mutate(lambda: store.view(args))

        async def add(args: dict[str, Any]) -> ToolResult:
            return await self._mutate(lambda: store.add(args["title"]))

        async def move(args: dict[str, Any]) -> ToolResult:
            return await self._mutate(lambda: store.move(args["id"], args["status"]))

        async def catalog(args: dict[str, Any]) -> ToolResult:
            query = args.get("query", "").strip().lower()
            items = (await self.snapshot())["catalog"]
            return result(
                {
                    "items": [
                        item
                        for item in items
                        if query in f"{item['title']} {item['description']}".lower()
                    ]
                }
            )

        async def connection_check(_: dict[str, Any]) -> ToolResult:
            return await self._mutate(store.connected)

        tools = [
            tool(
                "guide_status",
                "Read the shared guide",
                "Read the current tutorial step, view and sample board. Does not change the "
                "chosen step.",
                status,
                annotations=READ,
                meta=UI_META,
            ),
            tool(
                "guide_step",
                "Choose a guide step",
                "Move every open guide view to a named step; optionally record it as completed or "
                "skipped. Skipping never counts as completion. Does not change NimbleBrain "
                "settings.",
                step,
                {
                    "step": {"type": "string", "enum": list(STEP_IDS)},
                    "complete": {"type": "boolean"},
                    "skip": {"type": "boolean"},
                },
                required=("step",),
            ),
            tool(
                "guide_preferences",
                "Set guide preferences",
                "Choose guided or quick pace, and light, dark or host theme for Showcase only. Use "
                "the person's preference. Does not change NimbleBrain settings.",
                preferences,
                {
                    "pace": {"type": "string", "enum": ["guided", "quick"]},
                    "theme": {"type": "string", "enum": ["host", "light", "dark"]},
                },
            ),
            tool(
                "guide_view",
                "Focus the guide's illustration",
                "Pause or highlight a known element inside the guide. Keep scale fixed; adjust "
                "zoom only when asked, never repeatedly zoom in and out. No access to the "
                "NimbleBrain shell or browser.",
                view,
                {
                    "zoom": {"type": "number", "minimum": 0.75, "maximum": 1.6},
                    "playing": {"type": "boolean"},
                    "focus": {"anyOf": [{"type": "string", "enum": list(FOCUS)}, {"type": "null"}]},
                },
            ),
            tool(
                "board_add",
                "Add a sample task",
                "Add a task to the guide's practice board, separate from the real Tasks app.",
                add,
                {"title": {"type": "string", "minLength": 1, "maxLength": 120}},
                required=("title",),
            ),
            tool(
                "board_move",
                "Move a sample task",
                "Move a guide practice card. Every open view follows the same saved board.",
                move,
                {
                    "id": {"type": "string", "maxLength": 80},
                    "status": {"type": "string", "enum": ["todo", "doing", "done"]},
                },
                required=("id", "status"),
            ),
            tool(
                "catalog_list",
                "Explore apps and guides",
                "List or search included examples, built-in Tasks, guides and existing connection "
                "settings. Does not install apps or authorize accounts.",
                catalog,
                {"query": {"type": "string", "maxLength": 120}},
                annotations=READ,
            ),
        ]
        if self.host is not None:
            # The external endpoint has no Showcase screen, so it omits app-only tools.
            tools.extend(
                item
                for item in self._host_tools()
                if not external
                or "model" in (item.meta or {}).get("ui", {}).get("visibility", ["model"])
            )
        if external:
            tools.append(
                tool(
                    "guide_connection_check",
                    "Confirm the external guide connection",
                    "When the person asks to test this connection, record a timestamp visible in "
                    "Showcase. Proves an external MCP tool call, not a model provider or chat "
                    "reply.",
                    connection_check,
                    meta={"ui": {"visibility": ["model"]}},
                )
            )
        return tools

    def _host_tools(self) -> list[GuideTool]:
        host = self.host
        assert host is not None
        app = {"type": "string", "enum": ["todo-board", "crm"]}

        def invoke(method: str) -> Handler:
            async def action(args: dict[str, Any]) -> ToolResult:
                return result(await host.call(method, args))

            return action

        async def job(_: dict[str, Any]) -> ToolResult:
            observed = await self._read_host()
            installation = observed["installation"]
            data = {"job": observed.get("appJob")}
            error = installation.get("appJobError", installation.get("hostError"))
            if error is not None:
                data["error"] = error
            return result(data)

        definitions = [
            (
                "appPlan",
                tool(
                    "app_plan",
                    "Review app installation",
                    "Read-only plan: connect a prepared app server without package work, or review the full install plan for the chosen app. Lists exact local effects; workspace selection happens after confirmation. Grants no external account access.",
                    invoke("appPlan"),
                    {"app": app},
                    ("app",),
                    READ,
                ),
            ),
            (
                "appInstall",
                tool(
                    "app_install",
                    "Add an app",
                    "Called by Showcase's Install or Connect button after the person reviews the exact app_plan; hidden from the agent. Queues its connection-only or full local installation under existing package policy. The host's job can outlast a managed NimbleBrain restart. Returns a durable job; use app_job_status for verified tools and UI. Grants no external account access.",
                    invoke("appInstall"),
                    {
                        "app": app,
                        "planHash": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                        "confirm": {"type": "boolean", "const": True},
                    },
                    ("app", "planHash", "confirm"),
                    ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True),
                    # An install can restart NimbleBrain, so only the person's click in Showcase
                    # makes one. NimbleBrain refuses agent calls to app-only tools.
                    {"ui": {**UI_META["ui"], "visibility": ["app"]}},
                ),
            ),
            (
                "appStatus",
                tool(
                    "app_status",
                    "Check app status",
                    "Verify this app's actual process, tools, UI and workspace connection. Does not install or repair anything.",
                    invoke("appStatus"),
                    {"app": app},
                    ("app",),
                    READ,
                ),
            ),
            (
                "appLifecycle",
                tool(
                    "app_lifecycle",
                    "Start or stop an installed app",
                    "Change only an already registered app's verified local process, when the person asks. Does not install code or stop NimbleBrain.",
                    invoke("appLifecycle"),
                    {"app": app, "action": {"type": "string", "enum": ["start", "stop"]}},
                    ("app", "action"),
                    ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False),
                    UI_META,
                ),
            ),
            (
                "agentSetup",
                tool(
                    "guide_agent_setup",
                    "Show external agent setup",
                    "Read the exact local MCP configuration and setup commands for Claude Code or Codex. Writes no agent settings and returns no keys.",
                    invoke("agentSetup"),
                    {"agent": {"type": "string", "enum": ["claude", "codex"]}},
                    ("agent",),
                    READ,
                ),
            ),
        ]
        return [item for capability, item in definitions if host.capabilities[capability]] + [
            tool(
                "app_job_status",
                "Read installation progress",
                "Read the latest app install job, including real stages, failure or verified readiness. Does not start work.",
                job,
                annotations=READ,
            )
        ]

    async def notify(self) -> None:
        """Tell every open session, then every listener, that the saved guide changed."""
        for session in list(self._sessions):
            try:
                await session.send_resource_list_changed()
            except Exception:
                self._sessions.discard(session)
        for listener in list(self.listeners):
            listener()

    @contextlib.asynccontextmanager
    async def _lifespan(self, _server: FastMCP):
        self._users += 1
        if self._users == 1:
            try:
                self._last = self.store.read()["revision"]
            except (OSError, ValueError):
                self._last = None
            self._watcher = asyncio.create_task(self._watch())
            if self.host is not None:
                self._unsubscribe = self.host.subscribe(self._host_changed.set)
                self._host_changed.set()
                self._host_watcher = asyncio.create_task(self._watch_host())
        try:
            yield {}
        finally:
            self._users -= 1
            if self._users == 0 and self._watcher is not None:
                self._watcher.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._watcher
                self._watcher = None
                if self._unsubscribe is not None:
                    self._unsubscribe()
                    self._unsubscribe = None
                if self._host_watcher is not None:
                    self._host_watcher.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await self._host_watcher
                    self._host_watcher = None

    async def _watch_host(self) -> None:
        while True:
            await self._host_changed.wait()
            self._host_changed.clear()
            try:
                observed = await self._read_host()
                if (observed.get("appJob") or {}).get("state") == "ready":
                    self.store.complete("catalog")
            except (OSError, ValueError):
                pass  # Status reads report saved-file trouble without overwriting it.
            await self.notify()

    async def _watch(self) -> None:
        while True:
            await asyncio.sleep(POLL_SECONDS)
            try:
                revision = self.store.read()["revision"]
            except (OSError, ValueError):
                continue  # A status read reports the unreadable file; nothing overwrites it.
            if revision != self._last:
                self._last = revision
                await self.notify()


class _Sessions(Middleware):
    """Remember each initialized session so a saved change reaches all of them."""

    def __init__(self, guide: Guide):
        self._guide = guide

    async def on_initialize(self, context: MiddlewareContext, call_next):
        if context.fastmcp_context is not None:
            self._guide._sessions.add(context.fastmcp_context.session)
        return await call_next(context)
