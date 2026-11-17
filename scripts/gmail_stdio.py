"""Local workspace-mcp launcher: strict loopback OAuth callbacks, read-only Gmail.

Run with the isolated .providers/gmail Python. No upstream files are changed.
"""
from __future__ import annotations

import os
import sys


class CallbackOriginGuard:
    def __init__(self, app, *, port: int):
        self.app = app
        self.allowed = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            origins = [v.decode("latin1") for k, v in scope.get("headers", []) if k.lower() == b"origin"]
            if origins and (len(origins) != 1 or origins[0] not in self.allowed):
                from starlette.responses import PlainTextResponse
                await PlainTextResponse("Origin not allowed", status_code=403)(scope, receive, send)
                return
        await self.app(scope, receive, send)


def configure():
    from auth.oauth_callback_server import MinimalOAuthServer
    from starlette.middleware.trustedhost import TrustedHostMiddleware

    os.environ["MCP_SINGLE_USER_MODE"] = "0"
    os.environ["WORKSPACE_MCP_BASE_URI"] = "http://127.0.0.1"
    os.environ["WORKSPACE_MCP_HOST"] = "127.0.0.1"
    os.environ["OTEL_SDK_DISABLED"] = "true"
    os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = ""
    os.environ["OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"] = ""
    original = MinimalOAuthServer.__init__

    def guarded(self, *args, **kwargs):
        original(self, *args, **kwargs)
        self.app.add_middleware(CallbackOriginGuard, port=self.port)
        self.app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"], www_redirect=False)

    MinimalOAuthServer.__init__ = guarded


def main():
    configure()
    # Fixed arguments prevent an ambient env/host flag from expanding OAuth scope.
    for key in ("WORKSPACE_MCP_TOOLS", "WORKSPACE_MCP_PERMISSIONS", "WORKSPACE_MCP_READ_ONLY", "WORKSPACE_MCP_HTTP_PORT"):
        os.environ.pop(key, None)
    sys.argv = ["workspace-mcp", "--transport", "stdio", "--permissions", "gmail:readonly", "--tool-tier", "core"]
    from main import main as upstream_main
    upstream_main()


if __name__ == "__main__":
    main()
