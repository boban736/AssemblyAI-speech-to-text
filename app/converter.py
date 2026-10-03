import asyncio
from pathlib import Path


class ConvertError(RuntimeError):
    pass


async def to_mp3(src: Path, dst: Path, bitrate: str = "48k") -> None:
    """Любой аудио/видео вход -> mono 16 кГц mp3 (для речи этого с запасом хватает)."""
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-nostdin", "-y", "-loglevel", "error",
        "-i", str(src),
        "-vn", "-map", "0:a:0",
        "-ac", "1", "-ar", "16000",
        "-c:a", "libmp3lame", "-b:a", bitrate,
        str(dst),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, err = await proc.communicate()
    if proc.returncode != 0 or not dst.exists():
        msg = err.decode(errors="replace").strip().splitlines()
        raise ConvertError("ffmpeg: " + (msg[-1] if msg else f"код {proc.returncode}"))
