"""
Optional HTTP sidecar — exposes a single POST /handshake endpoint.

This is the one acceptable non-MCP endpoint: it allows an IDE plugin to
pre-warm the proxy's tool selection BEFORE opening its MCP stdio connection,
so that tools/list already reflects the right server set from the first call.

All other management (health, server list, metrics) is served via MCP-native
resources/read and tools/list.
"""
from __future__ import annotations

import sys
from typing import Any, Callable, Optional

from fastapi import FastAPI, HTTPException, Request, Security
from fastapi.security import APIKeyHeader
from pydantic import BaseModel

from .auth import authenticate, AuthError
from .config import AppConfig, CatalogueEntry

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


class HandshakeRequest(BaseModel):
    tech_stack: list[str] = []
    task_description: str = ""
    open_files: list[str] = []
    requirements: list[str] = []


class HandshakeResponse(BaseModel):
    activated_servers: list[str]
    active_tool_count: int
    budget_remaining: int
    message: str


def create_app(
    config: AppConfig,
    catalogue: list[CatalogueEntry],
    handshake_fn: Callable,
) -> FastAPI:
    """
    Factory that creates the FastAPI sidecar app.
    Receives references to the live config, catalogue, and the handshake function
    from proxy_server so state is shared.
    """
    from fastapi.middleware.cors import CORSMiddleware

    app = FastAPI(
        title="Dynamic MCP Proxy — HTTP Sidecar",
        description=(
            "Single pre-connection endpoint. All other proxy management "
            "is available via MCP-native resources/read and tools/list."
        ),
        version="0.1.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["POST"],
        allow_headers=["*"],
    )

    @app.post("/handshake", response_model=HandshakeResponse)
    async def handshake(
        body: HandshakeRequest,
        request: Request,
        api_key: Optional[str] = Security(_api_key_header),
    ) -> Any:
        """
        Pre-warm the proxy by sending project context before the MCP connection opens.
        The proxy activates relevant servers so tools/list is ready immediately.
        """
        import json as _json

        # Enforce auth when enabled
        bearer_token: Optional[str] = None
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            bearer_token = auth_header.removeprefix("Bearer ").strip()

        try:
            authenticate(bearer_token=bearer_token, api_key=api_key, config=config)
        except AuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc))

        try:
            result_str = handshake_fn(
                tech_stack=body.tech_stack,
                task_description=body.task_description,
                open_files=body.open_files,
                requirements=body.requirements,
            )
            result = _json.loads(result_str)
            return HandshakeResponse(
                activated_servers=result.get("activated_servers", []),
                active_tool_count=result.get("active_tool_count", 0),
                budget_remaining=result.get("budget_remaining", config.tool_budget),
                message=(
                    f"Activated {len(result.get('activated_servers', []))} server(s). "
                    f"Connect via MCP and call tools/list to see available tools."
                ),
            )
        except HTTPException:
            raise
        except Exception as exc:
            sys.stderr.write(f"[api] Handshake failed: {exc}\n")
            raise HTTPException(status_code=500, detail="Internal server error")

    @app.get("/health")
    async def health() -> dict:
        """Minimal liveness probe for container health checks."""
        return {"status": "ok"}

    return app
