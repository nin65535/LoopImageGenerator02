"""Validated local settings; relative storage paths follow the config file."""

import os
import tomllib
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    comfyui_url: str = "http://127.0.0.1:8188"
    storage_dir: Path = ROOT / "data"
    image_count: int = Field(default=10, ge=1)
    width: int = Field(default=512, ge=1)
    height: int = Field(default=512, ge=1)
    shutdown_grace: int = Field(default=5, ge=1)
    startup_timeout: int = Field(default=30, ge=1)

    @field_validator("comfyui_url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("ComfyUI URL must be an absolute HTTP(S) URL")
        return value.rstrip("/")

    @property
    def database_path(self) -> Path:
        return self.storage_dir / "loop-image-generator.sqlite3"


def load_settings(path: Path | None = None) -> Settings:
    explicit = path is not None or "LOOP_IMAGE_CONFIG" in os.environ
    path = (path or Path(os.environ.get("LOOP_IMAGE_CONFIG", ROOT / "config.toml"))).resolve()
    if not path.is_file() and not explicit:
        return Settings()
    with path.open("rb") as file:
        values = tomllib.load(file)
    storage = values.get("storage_dir", "data")
    if not isinstance(storage, str) or not storage.strip():
        raise ValueError("storage_dir must be a non-empty path string")
    values["storage_dir"] = (path.parent / storage).resolve()
    return Settings.model_validate(values)
