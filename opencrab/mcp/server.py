"""
OpenCrab MCP Server — stdio JSON-RPC implementation.

Implements the Model Context Protocol (MCP) over stdin/stdout so that
any MCP-compatible host (Claude Code, n8n, etc.) can use OpenCrab tools.

Protocol:
  - Transport: newline-delimited JSON over stdio
  - Methods handled: initialize, tools/list, tools/call
  - Each request:  {"jsonrpc":"2.0","id":N,"method":"...","params":{...}}
  - Each response: {"jsonrpc":"2.0","id":N,"result":{...}}
                or {"jsonrpc":"2.0","id":N,"error":{"code":-32XXX,"message":"..."}}

Reference: https://modelcontextprotocol.io/specification
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

from opencrab.config import get_settings
from opencrab.mcp.tools import TOOLS, dispatch_tool

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# JSON-RPC error codes
# ---------------------------------------------------------------------------
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


class MCPServer:
    """
    Minimal stdio MCP server compatible with Claude Code's MCP protocol.

    Usage:
        server = MCPServer()
        server.run()   # blocks forever, reading from stdin
    """

    def __init__(self) -> None:
        cfg = get_settings()
        self._name = cfg.mcp_server_name
        self._version = cfg.mcp_server_version

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def run(self) -> None:
        """
        Main event loop: read JSON-RPC requests from stdin, write responses
        to stdout. Runs until EOF or interrupt.
        """
        logger.info("OpenCrab MCP server starting (name=%s, version=%s)", self._name, self._version)

        for raw_line in sys.stdin:
            raw_line = raw_line.strip()
            if not raw_line:
                continue

            response = self._handle_raw(raw_line)
            if response is not None:
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()

        logger.info("OpenCrab MCP server shutting down (EOF).")

    # ------------------------------------------------------------------
    # Request handling
    # ------------------------------------------------------------------

    def _handle_raw(self, raw: str) -> dict[str, Any] | None:
        """Parse a raw JSON line and return a JSON-RPC response dict."""
        if not raw or not raw.strip():
            return None

        try:
            request = json.loads(raw)
        except json.JSONDecodeError as exc:
            return self._error_response(None, PARSE_ERROR, f"Parse error: {exc}")

        req_id = request.get("id")
        method = request.get("method")

        if not isinstance(method, str):
            return self._error_response(req_id, INVALID_REQUEST, "Missing or invalid 'method'.")

        params = request.get("params") or {}

        try:
            result = self._dispatch(method, params)
        except KeyError as exc:
            return self._error_response(req_id, METHOD_NOT_FOUND, str(exc))
        except TypeError as exc:
            return self._error_response(req_id, INVALID_PARAMS, f"Invalid params: {exc}")
        except Exception as exc:
            logger.exception("Internal error handling method '%s': %s", method, exc)
            return self._error_response(req_id, INTERNAL_ERROR, str(exc))

        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    def _dispatch(self, method: str, params: dict[str, Any]) -> Any:
        """Route a method to its handler."""
        if method == "initialize":
            return self._handle_initialize(params)
        elif method == "tools/list":
            return self._handle_tools_list(params)
        elif method == "tools/call":
            return self._handle_tools_call(params)
        elif method == "ping":
            return {"status": "ok", "server": self._name}
        else:
            raise KeyError(f"Method not found: '{method}'")

    # ------------------------------------------------------------------
    # Method handlers
    # ------------------------------------------------------------------

    def _handle_initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        Respond to the MCP initialize handshake.

        Returns server capabilities and protocol version.
        """
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {"listChanged": False},
            },
            "serverInfo": {
                "name": self._name,
                "version": self._version,
            },
            "instructions": (
                "OpenCrab exposes the MetaOntology OS grammar. "
                "Use ontology_manifest to explore the full grammar, "
                "then add nodes/edges and query the ontology."
            ),
        }

    def _handle_tools_list(self, params: dict[str, Any]) -> dict[str, Any]:
        """Return the list of all available MCP tools."""
        return {"tools": TOOLS}

    def _handle_tools_call(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        Execute a tool and return the result.

        Expected params: {"name": "tool_name", "arguments": {...}}
        """
        name = params.get("name")
        if not name:
            raise TypeError("'name' is required in tools/call params.")

        arguments = params.get("arguments") or {}

        try:
            result = dispatch_tool(name, arguments)
        except KeyError as exc:
            raise KeyError(str(exc)) from exc
        except Exception as exc:
            logger.warning("Tool '%s' raised: %s", name, exc)
            result = {"error": str(exc)}

        # MCP content format: wrap result in a content list
        content_text = json.dumps(result, ensure_ascii=False, default=str)
        return {
            "content": [
                {
                    "type": "text",
                    "text": content_text,
                }
            ]
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _error_response(
        req_id: Any, code: int, message: str
    ) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": code, "message": message},
        }


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Start the MCP server (called by cli.py serve command)."""
    import logging

    logging.basicConfig(
        level=logging.WARNING,  # keep stderr quiet while serving MCP on stdio
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )
    server = MCPServer()
    server.run()


if __name__ == "__main__":
    main()
