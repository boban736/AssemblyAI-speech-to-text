import os
import secrets
from pathlib import Path


def _bool(v: str) -> bool:
    return v.strip().lower() in ("1", "true", "yes", "on")


class Settings:
    def __init__(self) -> None:
        self.api_key = os.getenv("ASSEMBLYAI_API_KEY", "")
        self.password = os.getenv("APP_PASSWORD", "")
        self.secret_key = os.getenv("SECRET_KEY") or secrets.token_hex(32)
        self.data_dir = Path(os.getenv("DATA_DIR", "./data")).resolve()
        self.max_upload_mb = int(os.getenv("MAX_UPLOAD_MB", "500"))
        self.workers = max(1, int(os.getenv("WORKERS", "2")))
        self.speech_models = [
            m.strip() for m in os.getenv("SPEECH_MODELS", "universal-3-pro,universal-2").split(",") if m.strip()
        ]
        self.cookie_secure = _bool(os.getenv("COOKIE_SECURE", "false"))
        self.api_base = os.getenv("ASSEMBLYAI_BASE_URL", "https://api.assemblyai.com")
        self.poll_interval = float(os.getenv("POLL_INTERVAL", "3"))
