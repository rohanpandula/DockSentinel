from __future__ import annotations

import os
from dataclasses import dataclass



def _as_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class AppConfig:
    secret_key: str
    database_url: str
    runtime_lock_path: str
    start_coordinator: bool
    testing: bool

    @classmethod
    def from_env(cls) -> "AppConfig":
        testing = _as_bool(os.getenv("TESTING"), False)
        environment = os.getenv("FLASK_ENV", "development").strip().lower()
        secret_key = (os.getenv("SECRET_KEY") or "").strip()
        if not secret_key:
            if testing or environment == "development":
                secret_key = "dev-secret-key"
            else:
                raise RuntimeError("SECRET_KEY must be set when FLASK_ENV is not development")
        if environment != "development" and not testing:
            if secret_key.lower() in {"change-me", "dev-secret-key"}:
                raise RuntimeError(
                    "SECRET_KEY cannot use default placeholder values in non-development environments"
                )
            if len(secret_key) < 16:
                raise RuntimeError("SECRET_KEY must be at least 16 characters when FLASK_ENV is not development")
        default_database_url = (
            "sqlite:///./data/docksentinel.db" if environment == "development" else "sqlite:////data/docksentinel.db"
        )
        default_lock_path = "./data/runtime.lock" if environment == "development" else "/data/runtime.lock"
        return cls(
            secret_key=secret_key,
            database_url=os.getenv("DATABASE_URL", default_database_url),
            runtime_lock_path=os.getenv("RUNTIME_LOCK_PATH", default_lock_path),
            start_coordinator=_as_bool(os.getenv("START_COORDINATOR"), True),
            testing=testing,
        )
