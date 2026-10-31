"""Serve bundled skills through the MCP Skills extension (`io.modelcontextprotocol/skills`).

`skills/list` and `skills/get` answer with each skill's `SKILL.md` URI, its frontmatter, and the
file's sha256 digest and byte size. `resources/read` serves the same bytes at that `skill://` URI,
so a host can check what it reads against the listing.

FastMCP 3 has no hook for an extension's own methods: mcp 1.x validates every request against
its fixed `ClientRequest` union and answers any other method with -32602. At initialize this
middleware widens that union for its own session and declares the extension. FastMCP 4, on
mcp 2, adds a public extension API; this module goes away when the app moves to it.
"""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import mcp.types as mt
from fastmcp import FastMCP
from fastmcp.resources import TextResource
from fastmcp.server.middleware import Middleware, MiddlewareContext
from mcp.shared.exceptions import McpError

SKILLS_EXTENSION = "io.modelcontextprotocol/skills"


@dataclass(frozen=True)
class Skill:
    name: str
    uri: str
    path: Path
    title: str


class SkillsListParams(mt.RequestParams):
    cursor: str | None = None


class SkillsListRequest(mt.Request[SkillsListParams | None, Literal["skills/list"]]):
    method: Literal["skills/list"] = "skills/list"
    params: SkillsListParams | None = None


class SkillsGetParams(mt.RequestParams):
    uri: str


class SkillsGetRequest(mt.Request[SkillsGetParams, Literal["skills/get"]]):
    method: Literal["skills/get"] = "skills/get"
    params: SkillsGetParams


class SkillsListResult(mt.Result):
    skills: list[dict[str, Any]]


class SkillsGetResult(mt.Result):
    skill: dict[str, Any]


class SkillsRequest(mt.ClientRequest):
    """Every request mcp knows, plus the two this extension adds."""

    root: mt.ClientRequestType | SkillsListRequest | SkillsGetRequest  # ty: ignore[invalid-attribute-override]


def describe(skill: Skill, data: bytes) -> dict[str, Any]:
    header = data.decode("utf-8").split("---")
    if len(header) < 3 or not header[1].strip():
        raise ValueError(f"{skill.path.name} has no frontmatter.")
    frontmatter = {}
    for line in header[1].strip().split("\n"):
        key, _, value = line.partition(":")
        frontmatter[key] = value.strip()
    return {
        "uri": skill.uri,
        "frontmatter": frontmatter,
        "resources": [
            {
                "uri": skill.uri,
                "digest": f"sha256:{hashlib.sha256(data).hexdigest()}",
                "size": len(data),
            }
        ],
    }


class SkillsExtension(Middleware):
    def __init__(self, skills: Sequence[Skill]):
        self._files = [(skill, skill.path.read_bytes()) for skill in skills]
        self.descriptors = [describe(skill, data) for skill, data in self._files]

    def install(self, server: FastMCP) -> None:
        for skill, data in self._files:
            server.add_resource(
                TextResource(
                    uri=skill.uri,  # type: ignore[arg-type]
                    name=skill.name,
                    title=skill.title,
                    mime_type="text/markdown",
                    text=data.decode("utf-8"),
                )
            )
        handlers = server._mcp_server.request_handlers
        handlers[SkillsListRequest] = self._list  # ty: ignore[invalid-assignment]
        handlers[SkillsGetRequest] = self._get  # ty: ignore[invalid-assignment]
        server.add_middleware(self)

    async def on_initialize(self, context: MiddlewareContext, call_next):
        if context.fastmcp_context is not None:
            session = context.fastmcp_context.session
            session._receive_request_type = SkillsRequest
            options = session._init_options
            capabilities = options.capabilities
            extensions = (capabilities.model_extra or {}).get("extensions") or {}
            options.capabilities = capabilities.model_copy(
                update={"extensions": {**extensions, SKILLS_EXTENSION: {}}}
            )
        return await call_next(context)

    async def _list(self, request: SkillsListRequest) -> SkillsListResult:
        if request.params is not None and request.params.cursor is not None:
            raise McpError(mt.ErrorData(code=mt.INVALID_PARAMS, message="Unknown skill cursor."))
        return SkillsListResult(skills=self.descriptors)

    async def _get(self, request: SkillsGetRequest) -> SkillsGetResult:
        for descriptor in self.descriptors:
            if descriptor["uri"] == request.params.uri:
                return SkillsGetResult(skill=descriptor)
        raise McpError(mt.ErrorData(code=mt.INVALID_PARAMS, message="Unknown skill URI."))
