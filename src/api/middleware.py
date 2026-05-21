"""API middleware components."""

import time
import logging
import re
from typing import Callable
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

_BOUNDARY_RE = re.compile(
    r"^[A-Za-z0-9'()+_,./:=?-]{1,70}$"
)


class UploadBoundaryMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ) -> Response:
        status = None
        try:
            error = self._validate_upload_boundary(request)
            if error:
                status = "rejected"
                logger.warning("Rejected multipart upload: %s", error)
                return Response(
                    status_code=400,
                    content=f"Invalid multipart boundary: {error}",
                    headers={"X-Upload-Guard": "rejected"},
                )

            if self._is_multipart(request):
                status = "accepted"
                request.state.upload_boundary_validated = True

            response = await call_next(request)
            if status == "accepted":
                response.headers["X-Upload-Guard"] = "accepted"
            return response
        except Exception:
            logger.exception("Upload middleware failed before response")
            return Response(
                status_code=500,
                content="Upload middleware error",
                headers={"X-Upload-Guard": "error"},
            )
        finally:
            if hasattr(request.state, "upload_boundary_validated"):
                delattr(request.state, "upload_boundary_validated")

    def _validate_upload_boundary(self, request: Request) -> str:
        if not self._is_multipart(request):
            return ""

        boundary = self._extract_boundary(
            request.headers.get("content-type", "")
        )
        if boundary is None:
            return "missing"
        if not boundary:
            return "blank"
        if not _BOUNDARY_RE.fullmatch(boundary):
            return "malformed"
        return ""

    def _is_multipart(self, request: Request) -> bool:
        content_type = request.headers.get("content-type", "")
        media_type = content_type.split(";", 1)[0].strip().lower()
        return media_type == "multipart/form-data"

    def _extract_boundary(self, content_type: str):
        for part in content_type.split(";")[1:]:
            key, separator, value = part.strip().partition("=")
            if separator and key.lower() == "boundary":
                value = value.strip()
                if value.startswith('"') or value.endswith('"'):
                    if len(value) < 2 or not value.endswith('"'):
                        return ""
                    value = value[1:-1]
                return value
        return None


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ) -> Response:
        is_api = request.url.path.startswith("/api/v2")
        is_token_path = request.url.path == "/api/v2/auth/token"
        if is_api and not is_token_path:
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
            t for t in self._requests[client_ip]
            if now - t < self.window
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
