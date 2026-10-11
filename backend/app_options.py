"""Persist the model whitelist and additional image sizes independently of projects."""

from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from backend.comfyui import ComfyUIClient, ComfyUIError
from backend.config import Settings

# Curated complete SDXL checkpoints from the installed model inventory.
MODEL_CATALOG = (
    "boleromixIllustrious_v402.safetensors",
    "boleromixIllustrious_v900.safetensors",
    "boleromixNoobai_v16Ep.safetensors",
    "boleromixNoobai_v174Ep.safetensors",
    "boleromixPony_v170.safetensors",
    "boleromixPony_v220.safetensors",
    "boleromixPony_v233.safetensors",
    "hassakuXLIllustrious_v30.safetensors",
    "hassakuXLIllustrious_v32.safetensors",
    "hassakuXLIllustrious_v33.safetensors",
    "waiIllustriousSDXL_v160.safetensors",
    "waiNSFWIllustrious_v140.safetensors",
    "waiNSFWIllustrious_v150.safetensors",
)


class ImageSize(BaseModel):
    model_config = ConfigDict(extra="forbid")
    width: StrictInt = Field(ge=16, le=16384)
    height: StrictInt = Field(ge=16, le=16384)

    @model_validator(mode="after")
    def validate_dimensions(self):
        if self.width % 8 or self.height % 8:
            raise ValueError("幅・高さは8の倍数にしてください。")
        return self


FIXED_SIZES = [
    ImageSize(width=1024, height=1024),
    ImageSize(width=768, height=1344),
    ImageSize(width=1344, height=768),
]


class AppOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_whitelist: list[str] = Field(
        default_factory=lambda: [
            MODEL_CATALOG[0],
            "hassakuXLIllustrious_v33.safetensors",
            "waiIllustriousSDXL_v160.safetensors",
        ],
        max_length=100,
    )
    extra_sizes: list[ImageSize] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_choices(self):
        if len(set(self.model_whitelist)) != len(self.model_whitelist):
            raise ValueError("モデルが重複しています。")
        if any(name not in MODEL_CATALOG for name in self.model_whitelist):
            raise ValueError("このアプリの対象モデルを選んでください。")
        sizes = [(size.width, size.height) for size in FIXED_SIZES + self.extra_sizes]
        if len(sizes) != len(set(sizes)):
            raise ValueError("画像サイズが重複しています。")
        return self


class OptionsStore:
    def __init__(self, storage: Path):
        self.path = storage / "app-options.json"

    def read(self) -> AppOptions:
        if not self.path.exists():
            return AppOptions()
        return AppOptions.model_validate_json(self.path.read_text(encoding="utf-8"))

    def write(self, options: AppOptions):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        staged = self.path.with_suffix(".tmp")
        try:
            staged.write_text(options.model_dump_json(indent=2), encoding="utf-8")
            staged.replace(self.path)
        finally:
            staged.unlink(missing_ok=True)


async def installed_models(settings: Settings) -> list[str]:
    try:
        async with httpx.AsyncClient(trust_env=False) as http:
            client = ComfyUIClient(http, settings.comfyui_url)
            info = await client._request("GET", "/object_info/CheckpointLoaderSimple", 10)
        names = info["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"][0]
        if not isinstance(names, list) or any(not isinstance(name, str) for name in names):
            raise ValueError("Invalid checkpoint list")
        return names
    except (ComfyUIError, KeyError, IndexError, TypeError, ValueError) as exc:
        raise HTTPException(502, "ComfyUIのモデル一覧を取得できません。") from exc


def options_router(settings: Settings, store: OptionsStore) -> APIRouter:
    router = APIRouter(prefix="/api/settings", tags=["settings"])

    @router.get("")
    def read_options():
        options = store.read()
        return {**options.model_dump(), "fixed_sizes": [size.model_dump() for size in FIXED_SIZES]}

    @router.get("/models")
    async def models():
        installed = await installed_models(settings)
        return {"models": [name for name in MODEL_CATALOG if name in installed]}

    @router.put("")
    async def save_options(options: AppOptions):
        installed = await installed_models(settings)
        if any(name not in installed for name in options.model_whitelist):
            raise HTTPException(422, "実際に存在するモデルを選んでください。")
        try:
            store.write(options)
        except OSError as exc:
            raise HTTPException(500, "設定を保存できません。") from exc
        return options.model_dump()

    return router
