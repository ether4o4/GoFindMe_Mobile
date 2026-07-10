"""Environment-driven configuration.

All settings come from the process environment (optionally loaded from a .env by
run.sh). Defaults are safe for a single-user box bound to loopback.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


def resource_base() -> Path:
    """Directory that holds bundled assets (static/, legacy/, app/).

    Under a PyInstaller build this is the extraction dir (``sys._MEIPASS``);
    otherwise it's the repository root.
    """
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent.parent


def _bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "").strip())
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Settings:
    bind: str = os.environ.get("GOFINDME_BIND", "127.0.0.1")
    port: int = _int("GOFINDME_PORT", 8000)

    db_path: Path = Path(os.environ.get("GOFINDME_DB", "./data/gofindme.db")).resolve()
    uploads_dir: Path = Path(os.environ.get("GOFINDME_UPLOADS_DIR", "./data/uploads")).resolve()

    vault_mode: str = os.environ.get("GOFINDME_VAULT_MODE", "encrypted").strip().lower()
    vault_idle_minutes: int = _int("GOFINDME_VAULT_IDLE_MINUTES", 30)

    token_ttl_days: int = _int("GOFINDME_TOKEN_TTL_DAYS", 7)

    max_concurrency: int = max(1, _int("GOFINDME_MAX_CONCURRENCY", 4))

    allow_tool_mgmt: bool = _bool("GOFINDME_ALLOW_TOOL_MGMT", True)

    # httpx honors HTTPS_PROXY + SSL_CERT_FILE automatically via trust_env.
    ca_bundle: str | None = os.environ.get("GOFINDME_CA_BUNDLE") or os.environ.get("SSL_CERT_FILE")

    # Per-job stdout cap (bytes) to bound memory/DB growth.
    output_cap_bytes: int = _int("GOFINDME_OUTPUT_CAP", 5 * 1024 * 1024)

    # Per-file cap (bytes) for case evidence uploads.
    max_upload_bytes: int = max(1, _int("GOFINDME_MAX_UPLOAD_MB", 25)) * 1024 * 1024

    @property
    def vault_plaintext(self) -> bool:
        return self.vault_mode == "plaintext"


@lru_cache(maxsize=1)
def settings() -> Settings:
    s = Settings()
    s.db_path.parent.mkdir(parents=True, exist_ok=True)
    s.uploads_dir.mkdir(parents=True, exist_ok=True)
    return s
