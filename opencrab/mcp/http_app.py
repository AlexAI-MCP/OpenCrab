"""
OpenCrab MCP Server — Streamable HTTP (2025-03-26) transport.

Exposes the same MCP grammar as the stdio server over HTTP, reusing
``MCPServer.handle_request`` as the single JSON-RPC dispatch source. The
implementation is intentionally stateless: each POST is an independent
request/response exchange (no Mcp-Session-Id, no server→client SSE stream),
which is sufficient because every tool is request/response and the server
never pushes events.

``opencrab serve --transport http`` builds a lightweight app via ``create_app``.

Authentication is optional: when an ``auth_token`` is provided the ``/mcp``
route requires a matching ``Authorization: Bearer`` header (HMAC compare).
Run with a single uvicorn worker — the underlying chroma PersistentClient is
single-process only.
"""

from __future__ import annotations

import hmac
import os
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from opencrab.mcp.server import MCPServer


def _resolve_token(cli_token: str | None = None, cli_token_file: str | None = None) -> str | None:
    """
    Resolve the bearer token for the HTTP transport.

    Precedence: explicit CLI token > OPENCRAB_MCP_TOKEN env > token file
    (CLI ``--auth-token-file`` or OPENCRAB_MCP_TOKEN_FILE env). Returns None
    when no source is configured, which leaves the instance unauthenticated.
    """
    if cli_token:
        return cli_token.strip()
    env_token = os.environ.get("OPENCRAB_MCP_TOKEN", "").strip()
    if env_token:
        return env_token
    path = cli_token_file or os.environ.get("OPENCRAB_MCP_TOKEN_FILE")
    if path:
        return Path(path).read_text(encoding="utf-8").strip()
    return None


def mcp_router(auth_token: str | None = None) -> APIRouter:
    """
    Build the shared ``/mcp`` routes (POST / GET / DELETE).

    When ``auth_token`` is set, POSTs require a matching bearer token; otherwise
    the route is open. Dispatch is delegated to ``MCPServer.handle_request`` so
    stdio and HTTP share one source of truth.
    """
    router = APIRouter()
    server = MCPServer()  # constructed once; tool stores lazy-init on first call
    bearer = HTTPBearer(auto_error=False)

    def _check(creds: HTTPAuthorizationCredentials | None) -> None:
        if not auth_token:
            return  # unauthenticated instance
        if (
            creds is None
            or creds.scheme.lower() != "bearer"
            or not hmac.compare_digest(creds.credentials.strip(), auth_token)
        ):
            raise HTTPException(
                status_code=401,
                detail="Unauthorized",
                headers={"WWW-Authenticate": "Bearer"},
            )

    @router.post("/mcp")
    async def mcp_post(
        request: Request,
        creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    ):
        _check(creds)
        try:
            body = await request.json()
        except Exception:
            return JSONResponse(
                {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}},
                status_code=400,
            )
        # JSON-RPC batch: collect non-notification responses
        if isinstance(body, list):
            out = [r for r in (server.handle_request(item) for item in body) if r is not None]
            return Response(status_code=202) if not out else JSONResponse(out)
        resp = server.handle_request(body)
        # Notifications (no id) get no body → 202 Accepted
        return Response(status_code=202) if resp is None else JSONResponse(resp)

    @router.get("/mcp")
    async def mcp_get():
        # Stateless server offers no server→client SSE stream; per spec, 405.
        return Response(status_code=405, headers={"Allow": "POST, DELETE"})

    @router.delete("/mcp")
    async def mcp_delete():
        # Stateless: no session to terminate. Acknowledge.
        return Response(status_code=200)

    return router


def create_app(auth_token: str | None = None) -> FastAPI:
    """Lightweight FastAPI app for ``serve --transport http`` — MCP router + healthz."""
    app = FastAPI(docs_url=None, redoc_url=None)
    app.include_router(mcp_router(auth_token))

    @app.get("/healthz")
    async def healthz():  # auth-exempt: lets reverse proxies / monitoring probe freely
        return PlainTextResponse("ok")

    return app
