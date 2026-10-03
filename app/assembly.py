import asyncio
from pathlib import Path
from typing import AsyncIterator

import httpx


class AssemblyError(RuntimeError):
    pass


async def _file_chunks(path: Path, size: int = 1 << 20) -> AsyncIterator[bytes]:
    with path.open("rb") as f:
        while chunk := f.read(size):
            yield chunk


class AssemblyClient:
    def __init__(self, api_key: str, base_url: str, speech_models: list[str], poll_interval: float = 3.0):
        self.base = base_url.rstrip("/")
        self.speech_models = speech_models
        self.poll_interval = poll_interval
        self.headers = {"authorization": api_key}

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base, headers=self.headers,
            timeout=httpx.Timeout(60.0, read=300.0, write=300.0),
        )

    @staticmethod
    def _raise(r: httpx.Response, what: str) -> None:
        if r.is_success:
            return
        try:
            detail = r.json().get("error") or r.text
        except Exception:
            detail = r.text
        raise AssemblyError(f"{what}: HTTP {r.status_code} {detail}"[:500])

    async def upload(self, path: Path) -> str:
        async with self._client() as c:
            r = await c.post("/v2/upload", content=_file_chunks(path))
            self._raise(r, "upload")
            return r.json()["upload_url"]

    async def create_transcript(self, audio_url: str) -> str:
        body = {
            "audio_url": audio_url,
            "language_detection": True,
            "speaker_labels": True,
        }
        if self.speech_models:
            body["speech_models"] = self.speech_models
        async with self._client() as c:
            r = await c.post("/v2/transcript", json=body)
            self._raise(r, "create transcript")
            return r.json()["id"]

    async def wait(self, transcript_id: str, on_status=None) -> dict:
        async with self._client() as c:
            while True:
                r = await c.get(f"/v2/transcript/{transcript_id}")
                self._raise(r, "poll transcript")
                data = r.json()
                status = data.get("status")
                if on_status:
                    on_status(status)
                if status == "completed":
                    return data
                if status == "error":
                    raise AssemblyError(data.get("error") or "transcription failed")
                await asyncio.sleep(self.poll_interval)
