import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

TRANSCRIPT = {
    "id": "tr_1", "status": "completed", "text": "Привет мир. Hello world.",
    "language_code": "ru", "audio_duration": 3.2,
    "utterances": [
        {"speaker": "A", "text": "Привет мир.", "start": 0, "end": 1500},
        {"speaker": "B", "text": "Hello world.", "start": 1600, "end": 3200},
    ],
    "words": [],
}


class FakeClient:
    def __init__(self, fail: str | None = None):
        self.fail, self.uploaded = fail, []

    async def upload(self, path: Path) -> str:
        self.uploaded.append(path)
        return "https://cdn.example/upload/1"

    async def create_transcript(self, url: str) -> str:
        return "tr_1"

    async def wait(self, tid: str, on_status=None) -> dict:
        if self.fail:
            from app.assembly import AssemblyError
            raise AssemblyError(self.fail)
        return TRANSCRIPT


@pytest.fixture
def m4a(tmp_path) -> Path:
    p = tmp_path / "Новая запись.m4a"
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
         "-c:a", "aac", "-b:a", "128k", str(p)], check=True)
    return p


def make_app(tmp_path, client=None):
    s = Settings()
    s.data_dir, s.password, s.secret_key, s.workers = tmp_path / "data", "pw", "k", 1
    return create_app(s, client or FakeClient())


@pytest.fixture
def web(tmp_path):
    with TestClient(make_app(tmp_path)) as c:
        yield c


@pytest.fixture
def authed(web):
    assert web.post("/api/login", json={"password": "pw"}).status_code == 200
    return web


def wait_status(c, rid, want=("done", "error"), timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        r = c.get(f"/api/recordings/{rid}").json()
        if r["status"] in want:
            return r
        time.sleep(0.1)
    raise AssertionError("timeout, last status " + r["status"])
