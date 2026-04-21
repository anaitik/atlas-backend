"""
Observability middleware — request ID injection, timing, and access logging.
"""

from __future__ import annotations

import time
import uuid
import structlog
from starlette.datastructures import MutableHeaders

logger = structlog.get_logger()


class RequestContextMiddleware:
    """
    Attaches a unique request_id to every request using pure ASGI.
    Logs method/path/status/latency.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        # Extraction logic moved from request object to raw ASGI scope
        headers = MutableHeaders(scope=scope)
        request_id = headers.get("X-Request-ID", str(uuid.uuid4()))
        
        # We can't use request.state here easily without a Request object, 
        # but we can pass it down in scope if needed.
        # FastAPI/Starlette Use "state" key in scope.
        if "state" not in scope:
            scope["state"] = {}
        scope["state"]["request_id"] = request_id

        start = time.perf_counter()

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                latency_ms = round((time.perf_counter() - start) * 1000, 2)
                
                # Update headers in the outgoing message
                response_headers = MutableHeaders(scope=message)
                response_headers["X-Request-ID"] = request_id
                response_headers["X-Response-Time-Ms"] = str(latency_ms)

                # Log completion
                logger.info(
                    "request_completed",
                    request_id=request_id,
                    method=scope["method"],
                    path=scope["path"],
                    status=message["status"],
                    latency_ms=latency_ms,
                )
            await send(message)

        await self.app(scope, receive, send_wrapper)
