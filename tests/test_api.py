import io
import re
from urllib.parse import unquote

from fastapi.testclient import TestClient

from tests.conftest import FakeClient, make_app, wait_status


def up(c, path, name=None):
    with open(path, "rb") as f:
        return c.post("/api/upload", files=[("files", (name or path.name, f, "audio/x-m4a"))])


def test_requires_auth(web):
    assert web.get("/api/recordings").status_code == 401
    assert web.post("/api/upload", files=[("files", ("a.m4a", b"x"))]).status_code == 401
    assert web.get("/download/" + "0" * 32 + "/mp3").status_code == 401
    assert web.get("/api/me").json() == {"authenticated": False}
    assert web.get("/").status_code == 200  # статика (форма входа) открыта


def test_login(web):
    assert web.post("/api/login", json={"password": "bad"}).status_code == 401
    r = web.post("/api/login", json={"password": "pw"})
    assert r.status_code == 200 and "httponly" in r.headers["set-cookie"].lower()
    assert web.get("/api/me").json() == {"authenticated": True}
    web.post("/api/logout")
    assert web.get("/api/me").json() == {"authenticated": False}


def test_login_rate_limit(web):
    for _ in range(10):
        web.post("/api/login", json={"password": "bad"})
    assert web.post("/api/login", json={"password": "pw"}).status_code == 429


def test_full_cycle(authed, m4a):
    r = up(authed, m4a)
    rid = r.json()["files"][0]["id"]
    rec = wait_status(authed, rid)
    assert rec["status"] == "done", rec
    assert rec["language"] == "ru" and rec["name"] == "Новая запись.m4a"
    assert 0 < rec["mp3_size"] < rec["original_size"]
    assert [x["id"] for x in authed.get("/api/recordings").json()] == [rid]

    txt = authed.get(f"/download/{rid}/txt")
    assert txt.text.startswith("Спикер A: Привет мир.")
    assert unquote(txt.headers["content-disposition"]).endswith("Новая запись.txt")
    assert "-->" in authed.get(f"/download/{rid}/srt").text
    assert authed.get(f"/download/{rid}/mp3").content[:3] in (b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2")
    assert authed.get(f"/download/{rid}/original").content == m4a.read_bytes()
    assert authed.get(f"/audio/{rid}").status_code == 200

    assert authed.delete(f"/api/recordings/{rid}").status_code == 200
    assert authed.get(f"/api/recordings/{rid}").status_code == 404
    assert authed.get("/api/recordings").json() == []
    assert not (authed.app.state.settings.data_dir / "uploads" / rid).exists()


def test_batch_upload(authed, m4a):
    data = m4a.read_bytes()
    r = authed.post("/api/upload", files=[("files", (f"{i}.m4a", data, "audio/x-m4a")) for i in range(3)])
    ids = [f["id"] for f in r.json()["files"]]
    assert len(ids) == 3
    assert all(wait_status(authed, i)["status"] == "done" for i in ids)


def test_transcription_error_and_retry(tmp_path, m4a):
    fake = FakeClient(fail="bad audio")
    with TestClient(make_app(tmp_path, fake)) as c:
        c.post("/api/login", json={"password": "pw"})
        rid = up(c, m4a).json()["files"][0]["id"]
        rec = wait_status(c, rid)
        assert rec["status"] == "error" and "bad audio" in rec["error"]
        assert c.get(f"/download/{rid}/txt").status_code == 409
        fake.fail = None
        assert c.post(f"/api/recordings/{rid}/retry").status_code == 200
        assert wait_status(c, rid)["status"] == "done"
        assert len(fake.uploaded) == 1  # mp3 уже готов, повторно загрузили только раз после ошибки


def test_garbage_file_marks_error(authed):
    r = authed.post("/api/upload", files=[("files", ("x.m4a", io.BytesIO(b"junk"), "audio/x-m4a"))])
    rec = wait_status(authed, r.json()["files"][0]["id"])
    assert rec["status"] == "error" and "ffmpeg" in rec["error"]


def test_size_limit_and_empty(tmp_path):
    app = make_app(tmp_path)
    app.state.settings.max_upload_mb = 1
    with TestClient(app) as c:
        c.post("/api/login", json={"password": "pw"})
        r = c.post("/api/upload", files=[("files", ("big.m4a", b"0" * (2 << 20))), ("files", ("e.m4a", b""))])
        errs = [f["error"] for f in r.json()["files"]]
        assert len(errs) == 2 and "1 МБ" in errs[0]
        assert c.get("/api/recordings").json() == []


def test_bad_id_is_404(authed):
    for rid in ("../etc", "zz", "0" * 32):
        assert authed.get(f"/api/recordings/{rid}").status_code == 404
