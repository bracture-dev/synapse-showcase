"""The guide's MCP surface: shared state across routes, skills and change notices."""

import asyncio
import hashlib
import re

from fastmcp import Client
from mcp.types import ResourceListChangedNotification, ServerNotification

from synapse_showcase.guide import Guide
from synapse_showcase.loopback import create_http_app
from synapse_showcase.skills import (
    SkillsGetParams,
    SkillsGetRequest,
    SkillsGetResult,
    SkillsListRequest,
    SkillsListResult,
    SkillsRequest,
)
from synapse_showcase.state import GuideStore
from tests.conftest import PROJECT_ROOT, call, eventually, over_http, serve, state, tool_names


async def test_native_and_external_tools_share_saved_state_across_a_restart(data_file):
    async with serve(create_http_app(Guide(GuideStore(data_file)))) as base:
        async with over_http(base) as native, over_http(base, "/agent/mcp") as agent:
            assert "guide_connection_check" not in await tool_names(native)
            assert "guide_connection_check" in await tool_names(agent)
            await state(native, "guide_step", {"step": "board"})
            created = await state(agent, "board_add", {"title": "A shared sample"})
            card = created["cards"][-1]
            await state(native, "board_move", {"id": card["id"], "status": "doing"})
            saved = data_file.read_bytes()
            await state(native, "board_move", {"id": card["id"], "status": "doing"})
            assert data_file.read_bytes() == saved, "a move to the same column rewrites nothing"
            assert (await state(agent, "guide_status"))["cards"][-1]["status"] == "doing"

    async with Client(Guide(GuideStore(data_file)).make_server()) as reopened:
        current = await state(reopened, "guide_status")
    assert current["step"] == "board"
    assert current["cards"][-1]["title"] == "A shared sample"
    assert current["cards"][-1]["status"] == "doing"
    assert current["revision"] == 3


async def test_unreadable_progress_is_a_tool_error_and_stays_on_disk(data_file):
    data_file.parent.mkdir(parents=True)
    data_file.write_text("interrupted personal progress")
    async with Client(Guide(GuideStore(data_file)).make_server()) as client:
        result = await call(client, "guide_status")
        assert result.isError
        assert "could not be read" in result.content[0].text
        assert (await call(client, "board_add", {"title": "Not over it"})).isError
    assert data_file.read_text() == "interrupted personal progress"


async def test_arguments_are_checked_against_the_listed_schema(data_file):
    async with Client(Guide(GuideStore(data_file)).make_server()) as client:
        refused = await call(client, "guide_step", {"step": "body"})
        assert refused.isError
        assert refused.content[0].text.startswith(
            "Input validation error: Invalid arguments for tool guide_step: step:"
        )
        assert (await call(client, "guide_view", {"zoom": 2})).isError
        assert (await call(client, "board_add", {})).isError
        assert not data_file.exists()

        await state(client, "guide_view", {"focus": "agent", "zoom": 1.2})
        paused = await state(client, "guide_view", {"playing": True, "ignored": "x"})
        assert paused["view"] == {"zoom": 1.2, "playing": True, "focus": "agent"}
        cleared = await state(client, "guide_view", {"focus": None})
        assert cleared["view"] == {"zoom": 1.2, "playing": True, "focus": None}


async def test_the_guide_skill_is_discoverable_without_creating_saved_progress(data_file):
    async with Client(Guide(GuideStore(data_file)).make_server()) as client:
        extensions = client.initialize_result.capabilities.model_extra["extensions"]
        assert "io.modelcontextprotocol/skills" in extensions
        listing = await client.session.send_request(
            SkillsRequest(SkillsListRequest()), SkillsListResult
        )
        assert [skill["uri"] for skill in listing.skills] == [
            "skill://showcase/guide/SKILL.md",
            "skill://showcase/add-app/SKILL.md",
        ]
        for skill in listing.skills:
            assert skill["frontmatter"]["name"] in ("showcase-guide", "showcase-add-app")
            assert re.fullmatch(r"sha256:[a-f0-9]{64}", skill["resources"][0]["digest"])
            fetched = await client.session.send_request(
                SkillsRequest(SkillsGetRequest(params=SkillsGetParams(uri=skill["uri"]))),
                SkillsGetResult,
            )
            assert fetched.skill == skill
            contents = (await client.read_resource_mcp(skill["uri"])).contents[0]
            assert contents.mimeType == "text/markdown"
            served = contents.text.encode()
            assert skill["resources"][0]["digest"] == f"sha256:{hashlib.sha256(served).hexdigest()}"
            assert skill["resources"][0]["size"] == len(served)
            folder = skill["uri"].split("/")[-2]
            assert served == (PROJECT_ROOT / "skills" / folder / "SKILL.md").read_bytes()
    assert not data_file.exists()


async def test_persisted_writes_announce_a_change_and_reads_do_not(data_file):
    guide = Guide(GuideStore(data_file))
    notices: list[None] = []
    guide.listeners.add(lambda: notices.append(None))
    announced: list[ServerNotification] = []

    async def receive(message):
        if isinstance(message, ServerNotification) and isinstance(
            message.root, ResourceListChangedNotification
        ):
            announced.append(message)

    async with (
        Client(guide.make_server(), message_handler=receive) as native,
        Client(guide.make_server(external=True)) as agent,
    ):
        await state(native, "guide_status")
        await asyncio.sleep(0.3)
        assert notices == []
        await state(agent, "board_add", {"title": "Agent notification sample"})
        await eventually(lambda: notices and announced, timeout=1)
        assert len(notices) == 1
        assert len(announced) == 1, "the native view hears about the agent's write"
        await state(native, "guide_status")
        await state(native, "catalog_list")
        await asyncio.sleep(0.3)
        assert len(notices) == 1


async def test_the_module_server_saves_progress_in_the_mpak_workspace(server_module, tmp_path):
    async with Client(server_module.mcp) as client:
        await state(client, "board_add", {"title": "Saved in the workspace"})
    saved = GuideStore(tmp_path / "workspace" / "showcase" / "progress.json").read()
    assert saved["cards"][-1]["title"] == "Saved in the workspace"
