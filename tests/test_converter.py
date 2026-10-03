import pytest

from app.converter import ConvertError, to_mp3


async def test_m4a_to_mp3_smaller(m4a, tmp_path):
    out = tmp_path / "a.mp3"
    await to_mp3(m4a, out)
    assert out.exists() and out.stat().st_size > 0
    assert out.read_bytes()[:3] in (b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2")
    assert out.stat().st_size < m4a.stat().st_size


async def test_garbage_input_raises(tmp_path):
    bad = tmp_path / "x.m4a"
    bad.write_bytes(b"not audio")
    with pytest.raises(ConvertError):
        await to_mp3(bad, tmp_path / "x.mp3")
