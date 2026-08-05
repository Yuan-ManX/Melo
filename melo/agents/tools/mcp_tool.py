"""call_mcp tool — generic MCP (Model Context Protocol) server connector.

MCP servers expose tools / resources / prompts via JSON-RPC. This
tool is a thin client: given a server URL + method + params, it issues
a JSON-RPC call and returns the result.

Melo ships a minimal HTTP-based transport. A STDIO transport for
local MCP servers (filesystem, shell, browser) implements the same
surface for process-local integrations.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from melo.agents.tools.registry import Tool, ToolError

logger = logging.getLogger(__name__)


class CallMCPTool(Tool):
    """Call a method on an MCP server via HTTP JSON-RPC."""

    name = "call_mcp"
    description = (
        "Invoke a JSON-RPC method on an MCP server. Args: server (URL), "
        "method (str), params (dict). Returns: the server's JSON-RPC result."
    )

    def __init__(self, *, timeout: float = 30.0) -> None:
        self._timeout = timeout

    async def run(self, **kwargs: Any) -> Any:
        server = kwargs.get("server")
        method = kwargs.get("method")
        params = kwargs.get("params") or {}
        if not server or not method:
            raise ToolError("call_mcp requires 'server' and 'method'")

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params,
        }

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            try:
                resp = await client.post(server, json=payload)
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                raise ToolError(f"MCP HTTP call to {server} failed: {exc}") from exc

            try:
                data = resp.json()
            except json.JSONDecodeError as exc:
                raise ToolError(f"MCP server returned non-JSON: {exc}") from exc

        if "error" in data and data["error"]:
            err = data["error"]
            raise ToolError(
                f"MCP error {err.get('code')}: {err.get('message')}"
            )
        return data.get("result")
