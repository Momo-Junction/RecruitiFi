import base64
import binascii
import hmac
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from .database import connect
from .seed import seed

DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
HOSTED_DEMO = os.getenv("TALENTMATCH_HOSTED_DEMO") == "1"


def initialize_demo():
    if not HOSTED_DEMO:
        return
    if not os.getenv("TALENTMATCH_DEMO_PASSWORD"):
        raise RuntimeError("Set TALENTMATCH_DEMO_PASSWORD for the hosted demo.")
    with connect() as connection:
        empty = connection.execute("SELECT 1 FROM candidates LIMIT 1").fetchone() is None
    if empty:
        seed()


def configure_hosting(app: FastAPI):
    if not HOSTED_DEMO:
        return

    @app.middleware("http")
    async def require_demo_login(request: Request, call_next):
        if request.url.path == "/healthz":
            return await call_next(request)
        scheme, _, token = request.headers.get("Authorization", "").partition(" ")
        credentials = b""
        if scheme.lower() == "basic":
            try:
                credentials = base64.b64decode(token, validate=True)
            except (ValueError, binascii.Error):
                pass
        expected = f"demo:{os.environ['TALENTMATCH_DEMO_PASSWORD']}".encode()
        if not hmac.compare_digest(credentials, expected):
            return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="RecruitiFi"'})
        return await call_next(request)

    app.mount("/", StaticFiles(directory=DIST, html=True), name="frontend")
