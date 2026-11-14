import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .demo_auth import hosted_password, DemoAuthMiddleware
from .database import connect
from .seed import seed

DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
HOSTED_DEMO = os.getenv("TALENTMATCH_HOSTED_DEMO") == "1"


def initialize_demo():
    if not HOSTED_DEMO:
        return
    hosted_password()
    with connect() as connection:
        empty = connection.execute("SELECT 1 FROM candidates LIMIT 1").fetchone() is None
    if empty:
        seed()


def configure_hosting(app: FastAPI):
    if not HOSTED_DEMO:
        return

    app.add_middleware(DemoAuthMiddleware)

    app.mount("/", StaticFiles(directory=DIST, html=True), name="frontend")
