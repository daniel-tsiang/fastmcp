"""Tests for app tool global keys — stable identifiers that survive transforms."""

from __future__ import annotations

import mcp.types
import pytest

from fastmcp import FastMCP
from fastmcp.exceptions import NotFoundError
from fastmcp.server.apps import AppConfig
from fastmcp.server.auth import AuthContext
from fastmcp.server.providers.base import _APP_TOOL_REGISTRY
from fastmcp.tools.tool import Tool, ToolResult


def _get_text(result: ToolResult) -> str:
    """Extract text from the first content item of a tool result."""
    item = result.content[0]
    assert isinstance(item, mcp.types.TextContent)
    return item.text


@pytest.fixture(autouse=True)
def _clean_registry():
    """Clear the global app tool registry between tests."""
    _APP_TOOL_REGISTRY.clear()
    yield
    _APP_TOOL_REGISTRY.clear()


# ---------------------------------------------------------------------------
# Global key generation
# ---------------------------------------------------------------------------


class TestGlobalKeyGeneration:
    def test_app_only_tool_gets_global_key(self):
        mcp = FastMCP("test")

        @mcp.tool(app=AppConfig(resource_uri="ui://app/view.html", visibility=["app"]))
        def save() -> str:
            return "saved"

        assert len(_APP_TOOL_REGISTRY) == 1
        key = next(iter(_APP_TOOL_REGISTRY))
        assert key.startswith("save-")
        assert len(key) == len("save-") + 8

    def test_model_and_app_tool_gets_global_key(self):
        mcp = FastMCP("test")

        @mcp.tool(
            app=AppConfig(
                resource_uri="ui://app/view.html", visibility=["model", "app"]
            )
        )
        def search(q: str) -> str:
            return q

        assert len(_APP_TOOL_REGISTRY) == 1
        key = next(iter(_APP_TOOL_REGISTRY))
        assert key.startswith("search-")

    def test_model_only_tool_no_global_key(self):
        mcp = FastMCP("test")

        @mcp.tool
        def regular() -> str:
            return "hi"

        assert len(_APP_TOOL_REGISTRY) == 0

    def test_app_tool_without_visibility_no_global_key(self):
        """AppConfig without visibility defaults to model-only — no global key."""
        mcp = FastMCP("test")

        @mcp.tool(app=AppConfig(resource_uri="ui://app/view.html"))
        def widget() -> str:
            return "w"

        assert len(_APP_TOOL_REGISTRY) == 0

    def test_global_key_maps_to_tool_object(self):
        mcp = FastMCP("test")

        @mcp.tool(app=AppConfig(resource_uri="ui://app/view.html", visibility=["app"]))
        def action() -> str:
            return "done"

        key = next(iter(_APP_TOOL_REGISTRY))
        tool = _APP_TOOL_REGISTRY[key]
        assert isinstance(tool, Tool)
        assert tool.name == "action"

    def test_two_tools_get_different_keys(self):
        mcp = FastMCP("test")
        app = AppConfig(resource_uri="ui://app/view.html", visibility=["app"])

        @mcp.tool(app=app)
        def tool_a() -> str:
            return "a"

        @mcp.tool(app=app)
        def tool_b() -> str:
            return "b"

        keys = list(_APP_TOOL_REGISTRY.keys())
        assert len(keys) == 2
        assert keys[0] != keys[1]

    async def test_global_key_in_tool_meta(self):
        """The globalKey appears in the tool's meta["ui"] for the app UI."""
        mcp = FastMCP("test")

        @mcp.tool(app=AppConfig(resource_uri="ui://app/view.html", visibility=["app"]))
        def action() -> str:
            return "a"

        tools = await mcp.list_tools()
        assert len(tools) == 1
        meta = tools[0].meta
        assert meta is not None
        global_key = meta["ui"]["globalKey"]
        assert global_key.startswith("action-")
        assert global_key in _APP_TOOL_REGISTRY


# ---------------------------------------------------------------------------
# Call resolution — single server
# ---------------------------------------------------------------------------


class TestCallToolSingleServer:
    async def test_call_by_global_key(self):
        mcp = FastMCP("test")

        @mcp.tool(app=AppConfig(resource_uri="ui://app/view.html", visibility=["app"]))
        def greet(name: str) -> str:
            return f"hi {name}"

        global_key = next(iter(_APP_TOOL_REGISTRY))
        result = await mcp.call_tool(global_key, {"name": "world"})
        assert _get_text(result) == "hi world"

    async def test_call_by_local_name_still_works(self):
        mcp = FastMCP("test")

        @mcp.tool(app=AppConfig(resource_uri="ui://app/view.html", visibility=["app"]))
        def greet(name: str) -> str:
            return f"hi {name}"

        result = await mcp.call_tool("greet", {"name": "direct"})
        assert _get_text(result) == "hi direct"


# ---------------------------------------------------------------------------
# Call resolution — mounted servers (namespace transforms)
# ---------------------------------------------------------------------------


class TestCallToolMounted:
    async def test_global_key_through_namespace(self):
        child = FastMCP("child")

        @child.tool(
            app=AppConfig(resource_uri="ui://app/view.html", visibility=["app"])
        )
        def save(data: str) -> str:
            return f"saved: {data}"

        parent = FastMCP("parent")
        parent.mount(child, namespace="dashboard")

        global_key = next(iter(_APP_TOOL_REGISTRY))
        result = await parent.call_tool(global_key, {"data": "test"})
        assert _get_text(result) == "saved: test"

    async def test_namespaced_name_still_works(self):
        """Regular namespaced access works alongside global keys."""
        child = FastMCP("child")

        @child.tool(
            app=AppConfig(resource_uri="ui://app/view.html", visibility=["app"])
        )
        def save(data: str) -> str:
            return f"saved: {data}"

        parent = FastMCP("parent")
        parent.mount(child, namespace="dashboard")

        result = await parent.call_tool("dashboard_save", {"data": "normal"})
        assert _get_text(result) == "saved: normal"

    async def test_triple_nested_mount(self):
        """Global key resolves through A → B → C."""
        server_c = FastMCP("C")

        @server_c.tool(
            app=AppConfig(resource_uri="ui://app/view.html", visibility=["app"])
        )
        def deep_action() -> str:
            return "from C"

        server_b = FastMCP("B")
        server_b.mount(server_c, namespace="c")

        server_a = FastMCP("A")
        server_a.mount(server_b, namespace="b")

        global_key = next(iter(_APP_TOOL_REGISTRY))
        result = await server_a.call_tool(global_key, {})
        assert _get_text(result) == "from C"

    async def test_same_name_tools_on_different_children(self):
        """Two children with the same tool name resolve to correct child."""

        def make_child(val: str) -> FastMCP:
            child = FastMCP("child")

            @child.tool(
                app=AppConfig(resource_uri="ui://app/view.html", visibility=["app"])
            )
            def action() -> str:
                return val

            return child

        child1 = make_child("from-child1")
        child2 = make_child("from-child2")

        parent = FastMCP("parent")
        parent.mount(child1, namespace="a")
        parent.mount(child2, namespace="b")

        keys = list(_APP_TOOL_REGISTRY.keys())
        assert len(keys) == 2

        results = set()
        for k in keys:
            result = await parent.call_tool(k, {})
            results.add(_get_text(result))

        assert results == {"from-child1", "from-child2"}

    async def test_mount_without_namespace(self):
        """Global keys work even without a namespace."""
        child = FastMCP("child")

        @child.tool(
            app=AppConfig(resource_uri="ui://app/view.html", visibility=["app"])
        )
        def action() -> str:
            return "done"

        parent = FastMCP("parent")
        parent.mount(child)

        global_key = next(iter(_APP_TOOL_REGISTRY))
        result = await parent.call_tool(global_key, {})
        assert _get_text(result) == "done"


# ---------------------------------------------------------------------------
# list_tools behavior
# ---------------------------------------------------------------------------


class TestListToolsBehavior:
    async def test_global_key_not_a_tool_name(self):
        """Global keys are not tool names — they don't appear in list_tools."""
        child = FastMCP("child")

        @child.tool(
            app=AppConfig(resource_uri="ui://app/view.html", visibility=["app"])
        )
        def hidden() -> str:
            return "h"

        parent = FastMCP("parent")
        parent.mount(child, namespace="ns")

        tools = await parent.list_tools()
        tool_names = [t.name for t in tools]

        global_key = next(iter(_APP_TOOL_REGISTRY))
        assert global_key not in tool_names
        assert "ns_hidden" in tool_names

    async def test_global_key_exposed_in_meta(self):
        """The global key is available in meta for app UIs to reference."""
        child = FastMCP("child")

        @child.tool(
            app=AppConfig(resource_uri="ui://app/view.html", visibility=["app"])
        )
        def action() -> str:
            return "a"

        parent = FastMCP("parent")
        parent.mount(child, namespace="ns")

        tools = await parent.list_tools()
        tool = tools[0]
        assert tool.meta is not None
        global_key = tool.meta["ui"]["globalKey"]
        assert global_key.startswith("action-")
        assert global_key in _APP_TOOL_REGISTRY


# ---------------------------------------------------------------------------
# Auth enforcement
# ---------------------------------------------------------------------------


class TestAuthWithGlobalKeys:
    async def test_auth_fires_on_global_key_call(self):
        """Auth checks must still run when calling via global key."""
        mcp = FastMCP("test")

        async def deny_all(ctx: AuthContext) -> bool:
            return False

        @mcp.tool(
            app=AppConfig(resource_uri="ui://app/view.html", visibility=["app"]),
            auth=deny_all,
        )
        def protected() -> str:
            return "secret"

        global_key = next(iter(_APP_TOOL_REGISTRY))

        with pytest.raises(NotFoundError):
            await mcp.call_tool(global_key, {})
