"""Tag a reference image on the configured ComfyUI without database writes."""

import argparse
import asyncio
import json
from pathlib import Path

import httpx
from fastapi import HTTPException

from backend.comfyui import ComfyUIClient, ComfyUIError
from backend.config import load_settings
from backend.reference_images import MAX_BYTES
from backend.tagging import tag_image


async def run(args):
    with args.image.open("rb") as file:
        data = file.read(MAX_BYTES + 1)
    async with httpx.AsyncClient(trust_env=False) as http:
        result = await tag_image(
            ComfyUIClient(http, load_settings().comfyui_url),
            data,
            model=args.model,
            threshold=args.threshold,
            timeout=args.timeout,
        )
    print(json.dumps({"prompt_id": result.prompt_id, "tags": result.tags}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("--model", default="wd-v1-4-moat-tagger-v2")
    parser.add_argument("--threshold", type=float, default=0.35)
    parser.add_argument("--timeout", type=float, default=300)
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except (ComfyUIError, HTTPException, OSError, ValueError) as exc:
        print(
            json.dumps(
                {"error": str(exc), "prompt_id": getattr(exc, "prompt_id", None)},
                ensure_ascii=False,
            )
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
