"""Shared synthetic-demo protection, enabled only with TALENTMATCH_HOSTED_DEMO=1."""
import base64
import binascii
import os
import secrets

from starlette.responses import JSONResponse


def hosted_password():
    mode = os.environ.get("TALENTMATCH_HOSTED_DEMO", "0")
    if mode not in ("0", "1"):
        raise RuntimeError("TALENTMATCH_HOSTED_DEMO must be 0 or 1.")
    if mode == "0":
        return None
    password = os.environ.get("TALENTMATCH_DEMO_PASSWORD", "")
    if not password.strip():
        raise RuntimeError("TALENTMATCH_DEMO_PASSWORD is required for hosted demo mode.")
    return password.encode("utf-8")


class DemoAuthMiddleware:
    def __init__(self, app):
        self.app = app
        self.password = hosted_password()

    async def __call__(self, scope, receive, send):
        if self.password is None or scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        if scope["path"] == "/healthz" and scope["method"] in ("GET", "HEAD"):
            await self.app(scope, receive, send)
            return
        values = [value for name, value in scope["headers"] if name.lower() == b"authorization"]
        username, password = b"", b""
        if len(values) == 1:
            scheme, _, token = values[0].partition(b" ")
            if scheme.lower() == b"basic":
                try:
                    decoded = base64.b64decode(token.strip(), validate=True)
                    if b":" in decoded:
                        username, password = decoded.split(b":", 1)
                except (ValueError, binascii.Error):
                    pass
        valid_user = secrets.compare_digest(username, b"demo")
        valid_password = secrets.compare_digest(password, self.password)
        if not (valid_user and valid_password):
            response = JSONResponse(
                {"detail": "Authentication required."}, status_code=401,
                headers={
                    "WWW-Authenticate": 'Basic realm="RecruitiFi demo", charset="UTF-8"',
                    "Cache-Control": "no-store",
                },
            )
            await response(scope, receive, send)
            return

        async def private_send(message):
            if message["type"] == "http.response.start":
                message = dict(message)
                message["headers"] = [
                    (name, value) for name, value in message.get("headers", [])
                    if name.lower() != b"cache-control"
                ] + [(b"cache-control", b"no-store")]
            await send(message)

        await self.app(scope, receive, private_send)
