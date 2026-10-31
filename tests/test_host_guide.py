"""Exercise the optional host through the same MCP contract used by the retained UI."""

from fastmcp import Client

from synapse_showcase.guide import GUIDE_URI, Guide
from synapse_showcase.host import CAPABILITIES
from synapse_showcase.state import GuideStore
from tests.conftest import call, eventually, state, tool_names


class FakeHost:
    def __init__(self):
        self.capabilities = dict.fromkeys(CAPABILITIES, True)
        self.calls = []
        self.listeners = set()
        self.broken = False
        self.observed = {
            "installation": {"managed": True},
            "apps": [],
            "appJob": None,
            "browseConnectorsUrl": "https://example.invalid/connectors",
        }

    async def call(self, method, params):
        self.calls.append((method, params))
        if self.broken:
            raise RuntimeError("Host unavailable")
        return self.observed if method == "snapshot" else {"method": method, "params": params}

    def subscribe(self, listener):
        self.listeners.add(listener)
        return lambda: self.listeners.discard(listener)

    def changed(self):
        for listener in self.listeners:
            listener()


async def test_host_tools_preserve_confirmation_schema_and_forward_only_valid_inputs(data_file):
    host = FakeHost()
    async with Client(Guide(GuideStore(data_file), host).make_server()) as client:
        tools = {item.name: item for item in await client.list_tools()}
        assert {
            "app_plan",
            "app_install",
            "app_status",
            "app_job_status",
            "app_lifecycle",
            "guide_agent_setup",
        } <= tools.keys()
        assert not any(name.startswith("operator_") for name in tools)
        assert tools["app_install"].annotations.openWorldHint
        assert tools["app_install"].meta["ui"]["visibility"] == ["app"]
        assert tools["app_lifecycle"].annotations.destructiveHint
        for name in ("guide_status", "guide_step", "board_add", "app_install", "app_lifecycle"):
            assert tools[name].meta["ui"]["resourceUri"] == GUIDE_URI
        for args in (
            {"app": "crm"},
            {"app": "crm", "planHash": "a" * 64, "confirm": False},
            {"app": "crm", "planHash": "wrong", "confirm": True},
        ):
            assert (await call(client, "app_install", args)).isError
        assert not any(method == "appInstall" for method, _ in host.calls)
        approved = {"app": "crm", "planHash": "a" * 64, "confirm": True}
        installed = await state(client, "app_install", {**approved, "extra": "ignored"})
        assert installed == {"method": "appInstall", "params": approved}
        await state(client, "app_lifecycle", {"app": "crm", "action": "stop"})
        assert host.calls[-1] == ("appLifecycle", {"app": "crm", "action": "stop"})
        status = await state(client, "guide_status")
        assert status["capabilities"] == dict.fromkeys(CAPABILITIES, True)
        assert status["installation"] == {"managed": True}
        assert (
            next(item for item in status["catalog"] if item["action"] == "browse-connectors")[
                "browseUrl"
            ]
            == host.observed["browseConnectorsUrl"]
        )


async def test_host_failure_preserves_saved_guide_actions_and_resource_read(
    data_file, tmp_path, monkeypatch
):
    host = FakeHost()
    host.broken = True
    ui = tmp_path / "ui"
    ui.mkdir()
    ui.joinpath("index.html").write_text("<!doctype html><title>Static guide</title>")
    monkeypatch.setenv("SHOWCASE_UI_DIR", str(ui))
    async with Client(Guide(GuideStore(data_file), host).make_server()) as client:
        saved = await state(client, "board_add", {"title": "Survives host loss"})
        assert saved["cards"][-1]["title"] == "Survives host loss"
        assert "hostError" in saved["installation"]
        assert "Host status is unavailable" in (await state(client, "app_job_status"))["error"]
        data_file.write_text("unreadable personal progress")
        before = len(host.calls)
        read = (await client.read_resource_mcp(GUIDE_URI)).contents[0]
        assert read.mimeType == "text/html;profile=mcp-app"
        assert read.text == ui.joinpath("index.html").read_text()
        assert len(host.calls) == before
    assert data_file.read_text() == "unreadable personal progress"


async def test_host_events_notify_without_revision_and_ready_completes_catalog(data_file):
    host = FakeHost()
    store = GuideStore(data_file)
    store.step("board")
    guide = Guide(store, host)
    notices = []
    guide.listeners.add(lambda: notices.append(True))
    async with Client(guide.make_server()) as client:
        await eventually(lambda: notices)
        before = len(notices)
        revision = store.read()["revision"]
        host.changed()
        await eventually(lambda: len(notices) > before)
        assert store.read()["revision"] == revision
        host.observed["appJob"] = {"state": "ready"}
        host.changed()
        await eventually(lambda: "catalog" in store.read()["completed"])
        current = await state(client, "guide_status")
        assert current["step"] == "board"
        assert current["appJob"]["state"] == "ready"
    assert not host.listeners


async def test_external_endpoint_omits_app_only_install(data_file):
    async with Client(Guide(GuideStore(data_file), FakeHost()).make_server(external=True)) as agent:
        names = await tool_names(agent)
        assert "app_plan" in names and "app_install" not in names
        approved = {"app": "crm", "planHash": "a" * 64, "confirm": True}
        assert (await call(agent, "app_install", approved)).isError


async def test_standalone_has_no_host_tools_or_capabilities(data_file):
    async with Client(Guide(GuideStore(data_file)).make_server()) as client:
        names = await tool_names(client)
        assert "app_install" not in names and "app_job_status" not in names
        status = await state(client, "guide_status")
        assert status["capabilities"] == dict.fromkeys(CAPABILITIES, False)
        assert status["installation"] == {"managed": False}
    assert not data_file.exists()
