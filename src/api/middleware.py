"""API middleware components."""

import contextvars
import gzip
import logging
import time
from typing import Callable
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import Message, Receive, Scope, Send

logger = logging.getLogger(__name__)

body_guard_context = contextvars.ContextVar("body_guard_context", default=None)

MAX_COMPRESSED_BODY_BYTES = 1_048_576
MAX_DECOMPRESSED_BODY_BYTES = 2_097_152
MAX_GZIP_EXPANSION_RATIO = 20
BODY_GUARD_HEADER = "X-Body-Guard"


def _set_scope_header(scope: Scope, name: bytes, value: bytes) -> None:
    headers = [
        (key, existing_value)
        for key, existing_value in scope["headers"]
        if key.lower() != name
    ]
    headers.append((name, value))
    scope["headers"] = headers


def _remove_scope_header(scope: Scope, name: bytes) -> None:
    scope["headers"] = [
        (key, value)
        for key, value in scope["headers"]
        if key.lower() != name
    ]


class BodyGuardMiddleware:
    def __init__(
        self,
        app,
        max_compressed_bytes: int = MAX_COMPRESSED_BODY_BYTES,
        max_decompressed_bytes: int = MAX_DECOMPRESSED_BODY_BYTES,
        max_expansion_ratio: int = MAX_GZIP_EXPANSION_RATIO,
    ):
        self.app = app
        self.max_compressed_bytes = max_compressed_bytes
        self.max_decompressed_bytes = max_decompressed_bytes
        self.max_expansion_ratio = max_expansion_ratio

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        state = {"status": "checking", "encoding": "identity"}
        token = body_guard_context.set(state)
        scope.setdefault("state", {})["body_guard"] = state

        try:
            body = await self._read_body(receive)
            encoding = self._header(scope, b"content-encoding").lower()

            if encoding == "gzip":
                state["encoding"] = "gzip"
                accepted, response, body = self._guard_gzip_request(
                    scope,
                    body,
                )
                if not accepted:
                    state["status"] = "rejected"
                    await response(scope, self._empty_receive, send)
                    return

            state["status"] = "accepted"
            await self.app(
                scope,
                self._receive_body(body),
                self._send_with_guard_header(send),
            )
        finally:
            body_guard_context.reset(token)

    async def _read_body(self, receive: Receive) -> bytes:
        chunks = []
        more_body = True

        while more_body:
            message = await receive()
            chunks.append(message.get("body", b""))
            more_body = message.get("more_body", False)

        return b"".join(chunks)

    @staticmethod
    async def _empty_receive() -> Message:
        return {"type": "http.request", "body": b"", "more_body": False}

    @staticmethod
    def _receive_body(body: bytes):
        sent = False

        async def receive() -> Message:
            nonlocal sent
            if sent:
                return {
                    "type": "http.request",
                    "body": b"",
                    "more_body": False,
                }
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}

        return receive

    @staticmethod
    def _send_with_guard_header(send: Send):
        async def send_with_header(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((BODY_GUARD_HEADER.lower().encode(), b"ok"))
                message["headers"] = headers
            await send(message)

        return send_with_header

    @staticmethod
    def _header(scope: Scope, name: bytes) -> str:
        for key, value in scope["headers"]:
            if key.lower() == name:
                return value.decode()
        return ""

    def _guard_gzip_request(self, scope: Scope, body: bytes):
        if len(body) > self.max_compressed_bytes:
            return False, self._reject("compressed body too large"), body

        try:
            decompressed = gzip.decompress(body)
        except (OSError, EOFError, gzip.BadGzipFile):
            return (
                False,
                self._reject("invalid gzip body", status_code=400),
                body,
            )

        if len(decompressed) > self.max_decompressed_bytes:
            return False, self._reject("decompressed body too large"), body

        expansion_ratio = len(decompressed) / max(len(body), 1)
        if expansion_ratio > self.max_expansion_ratio:
            return False, self._reject("gzip expansion ratio too high"), body

        _remove_scope_header(scope, b"content-encoding")
        _set_scope_header(
            scope,
            b"content-length",
            str(len(decompressed)).encode(),
        )
        return True, None, decompressed

    @staticmethod
    def _reject(reason: str, status_code: int = 413) -> Response:
        logger.warning("Rejected request body: %s", reason)
        response = Response(status_code=status_code, content=reason)
        response.headers[BODY_GUARD_HEADER] = "rejected"
        return response


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ) -> Response:
        if (
            request.url.path.startswith("/api/v2")
            and request.url.path != "/api/v2/auth/token"
        ):
            token = request.headers.get("Authorization", "")
            if not token.startswith("Bearer "):
                return Response(status_code=401, content="Unauthorized")
        return await call_next(request)


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_requests: int = 100, window: int = 60):
        super().__init__(app)
        self.max_requests = max_requests
        self.window = window
        self._requests = {}

    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ) -> Response:
        client_ip = request.client.host if request.client else "unknown"
        now = time.time()

        if client_ip not in self._requests:
            self._requests[client_ip] = []

        self._requests[client_ip] = [
            t for t in self._requests[client_ip] if now - t < self.window
        ]

        if len(self._requests[client_ip]) >= self.max_requests:
            return Response(status_code=429, content="Too many requests")

        self._requests[client_ip].append(now)
        return await call_next(request)


class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ) -> Response:
        start = time.time()
        response = await call_next(request)
        duration = time.time() - start
        logger.info(
            "%s %s %s %.3fs",
            request.method,
            request.url.path,
            response.status_code,
            duration,
        )
        return response

# 2019-03-01T18:35:19 update

# 2019-04-03T13:22:05 update

# 2019-04-30T17:18:49 update

# 2019-08-20T09:29:03 update

# 2019-08-30T15:52:06 update

# 2019-11-23T16:58:42 update

# 2020-02-18T10:04:07 update

# 2020-04-21T17:35:30 update

# 2020-05-22T11:10:34 update

# 2020-07-02T12:31:26 update

# 2020-07-05T13:52:59 update

# 2020-08-21T20:36:45 update

# 2021-01-19T09:17:15 update

# 2021-01-29T11:34:24 update

# 2021-02-04T15:21:21 update

# 2021-04-19T19:23:15 update

# 2021-05-20T16:50:15 update

# 2021-06-22T19:23:44 update

# 2021-09-09T13:44:55 update

# 2021-09-16T09:30:20 update

# 2021-10-14T20:42:33 update

# 2021-12-28T16:39:14 update

# 2022-01-26T19:07:27 update

# 2022-01-28T08:03:41 update

# 2022-03-23T12:17:02 update

# 2022-04-06T12:12:27 update

# 2022-04-21T14:53:01 update

# 2022-06-30T08:37:32 update

# 2022-07-06T10:44:45 update

# 2022-11-02T11:12:47 update

# 2022-11-15T20:54:21 update

# 2022-11-23T14:13:34 update

# 2023-01-26T10:03:44 update

# 2023-02-09T17:08:10 update

# 2023-02-16T10:04:00 update

# 2023-03-14T11:52:03 update

# 2023-04-10T12:42:07 update

# 2023-04-26T10:43:39 update

# 2023-06-27T08:18:07 update

# 2023-08-30T15:30:40 update

# 2023-08-30T14:10:05 update

# 2023-10-09T18:32:46 update

# 2023-11-21T20:35:55 update

# 2024-03-07T19:17:39 update

# 2024-04-01T18:06:19 update

# 2024-07-18T15:37:34 update

# 2024-07-25T09:21:53 update

# 2024-08-12T14:24:22 update

# 2024-11-18T08:50:54 update

# 2025-04-08T12:43:05 update

# 2025-06-03T08:10:47 update

# 2025-06-12T08:37:52 update

# 2025-06-17T08:36:56 update

# 2025-07-02T18:09:42 update

# 2025-07-22T12:39:21 update

# 2025-10-13T12:13:46 update

# 2025-12-05T09:44:22 update

# 2025-12-22T18:34:47 update

# 2026-01-26T15:36:23 update

# 2026-02-13T12:36:40 update

# 2026-02-26T11:07:15 update

# 2026-03-19T11:00:17 update

# 2026-03-27T12:58:53 update

# 2026-05-12T17:19:36 update
