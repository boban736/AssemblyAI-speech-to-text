import json

import httpx
import pytest
import respx

from app.assembly import AssemblyClient, AssemblyError

BASE = "https://api.assemblyai.com"


def client():
    return AssemblyClient("KEY", BASE, ["universal-3-pro", "universal-2"], poll_interval=0)


@respx.mock
async def test_full_flow(tmp_path):
    f = tmp_path / "a.mp3"
    f.write_bytes(b"x" * 10)
    up = respx.post(f"{BASE}/v2/upload").mock(return_value=httpx.Response(200, json={"upload_url": "https://u/1"}))
    cr = respx.post(f"{BASE}/v2/transcript").mock(return_value=httpx.Response(200, json={"id": "t1"}))
    respx.get(f"{BASE}/v2/transcript/t1").mock(side_effect=[
        httpx.Response(200, json={"status": "queued"}),
        httpx.Response(200, json={"status": "processing"}),
        httpx.Response(200, json={"status": "completed", "text": "hi"}),
    ])
    c = client()
    url = await c.upload(f)
    tid = await c.create_transcript(url)
    data = await c.wait(tid)
    assert (url, tid, data["text"]) == ("https://u/1", "t1", "hi")
    assert up.calls[0].request.headers["authorization"] == "KEY"
    assert up.calls[0].request.content == b"x" * 10
    body = json.loads(cr.calls[0].request.content)
    assert body == {"audio_url": "https://u/1", "language_detection": True, "speaker_labels": True,
                    "speech_models": ["universal-3-pro", "universal-2"]}


@respx.mock
async def test_transcript_error():
    respx.get(f"{BASE}/v2/transcript/t1").mock(
        return_value=httpx.Response(200, json={"status": "error", "error": "no speech"}))
    with pytest.raises(AssemblyError, match="no speech"):
        await client().wait("t1")


@respx.mock
async def test_http_error(tmp_path):
    f = tmp_path / "a.mp3"
    f.write_bytes(b"x")
    respx.post(f"{BASE}/v2/upload").mock(return_value=httpx.Response(401, json={"error": "Invalid API key"}))
    with pytest.raises(AssemblyError, match="Invalid API key"):
        await client().upload(f)
