"""API middleware components."""

import asyncio
import contextvars
import time
import logging
from typing import Callable
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response

logger = logging.getLogger(__name__)
_timeout_state = contextvars.ContextVar("request_timeout_state", default=None)


def get_request_timeout_state():
    return _timeout_state.get()


class TimeoutMiddleware:
    def __init__(self, app, timeout_seconds: float = 30.0):
        self.app = app
        self.timeout_seconds = timeout_seconds

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        state = {"active": True, "timed_out": False}
        token = _timeout_state.set(state)
        response_started = False
        response_start = None

        async def guarded_send(message):
            nonlocal response_started, response_start
            if message["type"] == "http.response.start":
                response_start = self._with_timeout_headers(
                    message,
                    status="enforced",
                )
                return

            if message["type"] == "http.response.body":
                if response_start is not None and not response_started:
                    await send(response_start)
                    response_started = True
                await send(message)
                return

            await send(message)

        try:
            await asyncio.wait_for(
                self.app(scope, receive, guarded_send),
                timeout=self.timeout_seconds,
            )
            if response_start is not None and not response_started:
                await send(response_start)
                await send({"type": "http.response.body", "body": b""})
        except asyncio.TimeoutError:
            state["timed_out"] = True
            self._clear_timeout_state(token, state)
            logger.warning(
                "request timeout method=%s path=%s timeout=%.3fs",
                scope.get("method", ""),
                scope.get("path", ""),
                self.timeout_seconds,
            )
            if response_started:
                await send(
                    {
                        "type": "http.response.body",
                        "body": b"",
                        "more_body": False,
                    }
                )
                return

            response = PlainTextResponse(
                "Request timed out",
                status_code=504,
                headers={
                    "X-Request-Timeout": "exceeded",
                    "X-Request-Timeout-Cleared": "true",
                },
            )
            await response(scope, receive, send)
        except Exception as exc:
            self._clear_timeout_state(token, state)
            logger.error(
                "request failed method=%s path=%s error_type=%s",
                scope.get("method", ""),
                scope.get("path", ""),
                type(exc).__name__,
            )
            if response_started:
                raise

            response = PlainTextResponse(
                "Internal Server Error",
                status_code=500,
                headers={
                    "X-Request-Timeout": "error",
                    "X-Request-Timeout-Cleared": "true",
                },
            )
            await response(scope, receive, send)
        finally:
            if get_request_timeout_state() is state:
                self._clear_timeout_state(token, state)

    def _clear_timeout_state(self, token, state) -> None:
        state["active"] = False
        _timeout_state.reset(token)

    def _with_timeout_headers(self, message, status: str):
        headers = list(message.get("headers", []))
        headers.extend(
            [
                (b"x-request-timeout", status.encode("ascii")),
                (b"x-request-timeout-cleared", b"true"),
            ]
        )
        return {**message, "headers": headers}


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
