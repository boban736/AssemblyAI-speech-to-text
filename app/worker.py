import asyncio
import logging
import shutil
from pathlib import Path

from .assembly import AssemblyClient
from .config import Settings
from .converter import to_mp3
from .db import DB

log = logging.getLogger("worker")


def rec_dir(settings: Settings, rid: str) -> Path:
    return settings.data_dir / "uploads" / rid


def original_path(settings: Settings, rec: dict) -> Path:
    return rec_dir(settings, rec["id"]) / f"original.{rec['original_ext']}"


def mp3_path(settings: Settings, rid: str) -> Path:
    return rec_dir(settings, rid) / "audio.mp3"


class Pipeline:
    def __init__(self, settings: Settings, db: DB, client: AssemblyClient):
        self.s, self.db, self.client = settings, db, client
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self._tasks: list[asyncio.Task] = []

    def start(self) -> None:
        for rid in self.db.pending_ids():  # докручиваем то, что оборвал рестарт
            self.queue.put_nowait(rid)
        self._tasks = [asyncio.create_task(self._run()) for _ in range(self.s.workers)]

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    def submit(self, rid: str) -> None:
        self.queue.put_nowait(rid)

    async def _run(self) -> None:
        while True:
            rid = await self.queue.get()
            try:
                await self.process(rid)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                log.exception("processing %s failed", rid)
                if self.db.get(rid):
                    self.db.update(rid, status="error", error=str(e)[:500])
            finally:
                self.queue.task_done()

    async def process(self, rid: str) -> None:
        rec = self.db.get(rid)
        if not rec:
            return
        src = original_path(self.s, rec)
        dst = mp3_path(self.s, rid)

        if not dst.exists():
            self.db.update(rid, status="converting", error=None)
            await to_mp3(src, dst)
        self.db.update(rid, mp3_size=dst.stat().st_size)

        aid = rec.get("assembly_id")
        if not aid:
            self.db.update(rid, status="uploading")
            url = await self.client.upload(dst)
            aid = await self.client.create_transcript(url)
            self.db.update(rid, assembly_id=aid)

        self.db.update(rid, status="transcribing")
        data = await self.client.wait(aid)
        if not self.db.get(rid):  # удалили, пока ждали
            return
        self.db.update(
            rid,
            status="done",
            text=data.get("text") or "",
            utterances=data.get("utterances"),
            words=data.get("words"),
            language=data.get("language_code"),
            duration=data.get("audio_duration"),
        )

    def remove_files(self, rid: str) -> None:
        shutil.rmtree(rec_dir(self.s, rid), ignore_errors=True)
