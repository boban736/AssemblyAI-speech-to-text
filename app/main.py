import hmac
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from itsdangerous import BadSignature, URLSafeTimedSerializer
from pydantic import BaseModel

from .assembly import AssemblyClient
from .config import Settings
from .db import DB
from .formats import to_srt, to_txt
from .worker import Pipeline, mp3_path, original_path, rec_dir

STATIC = Path(__file__).parent / "static"
COOKIE = "session"
SESSION_TTL = 30 * 24 * 3600


class LoginBody(BaseModel):
    password: str


def create_app(settings: Settings | None = None, client: AssemblyClient | None = None) -> FastAPI:
    s = settings or Settings()
    s.data_dir.mkdir(parents=True, exist_ok=True)
    (s.data_dir / "uploads").mkdir(exist_ok=True)
    db = DB(s.data_dir / "transcripts.db")
    client = client or AssemblyClient(s.api_key, s.api_base, s.speech_models, s.poll_interval)
    pipeline = Pipeline(s, db, client)
    signer = URLSafeTimedSerializer(s.secret_key, salt="session")
    fails: dict[str, list[float]] = {}

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        pipeline.start()
        yield
        await pipeline.stop()

    app = FastAPI(title="Voice transcriber", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    def authed(request: Request) -> bool:
        token = request.cookies.get(COOKIE)
        if not token:
            return False
        try:
            return signer.loads(token, max_age=SESSION_TTL) == "ok"
        except BadSignature:
            return False

    def require_auth(request: Request) -> None:
        if not authed(request):
            raise HTTPException(401, "Требуется вход")

    def get_rec(rid: str) -> dict:
        rec = db.get(rid) if re.fullmatch(r"[0-9a-f]{32}", rid) else None
        if not rec:
            raise HTTPException(404, "Запись не найдена")
        return rec

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @app.get("/api/me")
    def me(request: Request):
        return {"authenticated": authed(request)}

    @app.post("/api/login")
    def login(body: LoginBody, request: Request, response: Response):
        ip = request.client.host if request.client else "?"
        now = time.time()
        recent = [t for t in fails.get(ip, []) if now - t < 300]
        if len(recent) >= 10:
            raise HTTPException(429, "Слишком много попыток, подождите несколько минут")
        if not s.password or not hmac.compare_digest(body.password.encode(), s.password.encode()):
            recent.append(now)
            fails[ip] = recent
            raise HTTPException(401, "Неверный пароль")
        fails.pop(ip, None)
        response.set_cookie(
            COOKIE, signer.dumps("ok"), max_age=SESSION_TTL,
            httponly=True, samesite="lax", secure=s.cookie_secure,
        )
        return {"ok": True}

    @app.post("/api/logout")
    def logout(response: Response):
        response.delete_cookie(COOKIE)
        return {"ok": True}

    @app.post("/api/upload", dependencies=[Depends(require_auth)])
    async def upload(files: list[UploadFile] = File(...)):
        limit = s.max_upload_mb * 1024 * 1024
        created = []
        for f in files:
            name = Path(f.filename or "recording").name or "recording"
            ext = re.sub(r"[^a-z0-9]", "", Path(name).suffix.lower())[:8] or "bin"
            rid = db.create(name, ext)
            d = rec_dir(s, rid)
            d.mkdir(parents=True, exist_ok=True)
            path = d / f"original.{ext}"
            size = 0
            too_big = False
            with path.open("wb") as out:
                while chunk := await f.read(1 << 20):
                    size += len(chunk)
                    if size > limit:
                        too_big = True
                        break
                    out.write(chunk)
            if too_big or size == 0:
                pipeline.remove_files(rid)
                db.delete(rid)
                created.append({"name": name, "error": f"Файл больше {s.max_upload_mb} МБ" if too_big else "Пустой файл"})
                continue
            db.update(rid, original_size=size)
            pipeline.submit(rid)
            created.append({"id": rid, "name": name})
        return {"files": created}

    @app.get("/api/recordings", dependencies=[Depends(require_auth)])
    def list_recordings():
        return db.list_all()

    @app.get("/api/recordings/{rid}", dependencies=[Depends(require_auth)])
    def get_recording(rid: str):
        rec = get_rec(rid)
        rec.pop("words", None)
        return rec

    @app.post("/api/recordings/{rid}/retry", dependencies=[Depends(require_auth)])
    def retry(rid: str):
        rec = get_rec(rid)
        if rec["status"] != "error":
            raise HTTPException(409, "Повтор возможен только для ошибок")
        db.update(rid, status="queued", error=None)
        pipeline.submit(rid)
        return {"ok": True}

    @app.delete("/api/recordings/{rid}", dependencies=[Depends(require_auth)])
    def delete_recording(rid: str):
        get_rec(rid)
        db.delete(rid)
        pipeline.remove_files(rid)
        return {"ok": True}

    @app.get("/download/{rid}/{kind}", dependencies=[Depends(require_auth)])
    def download(rid: str, kind: str):
        rec = get_rec(rid)
        base = Path(rec["name"]).stem or "recording"

        def disp(filename: str) -> dict:
            return {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"}

        if kind == "original":
            p = original_path(s, rec)
            if not p.exists():
                raise HTTPException(404)
            return FileResponse(p, headers=disp(rec["name"]))
        if kind == "mp3":
            p = mp3_path(s, rid)
            if not p.exists():
                raise HTTPException(404, "mp3 ещё не готов")
            return FileResponse(p, media_type="audio/mpeg", headers=disp(base + ".mp3"))
        if kind in ("txt", "srt"):
            if rec["status"] != "done":
                raise HTTPException(409, "Транскрипт ещё не готов")
            body = to_txt(rec) if kind == "txt" else to_srt(rec)
            return Response(body, media_type="text/plain; charset=utf-8", headers=disp(f"{base}.{kind}"))
        raise HTTPException(404)

    @app.get("/audio/{rid}", dependencies=[Depends(require_auth)])
    def stream_audio(rid: str):
        get_rec(rid)
        p = mp3_path(s, rid)
        if not p.exists():
            raise HTTPException(404)
        return FileResponse(p, media_type="audio/mpeg")

    app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
    app.state.pipeline, app.state.db, app.state.settings = pipeline, db, s
    return app


def app_factory() -> FastAPI:
    return create_app()
