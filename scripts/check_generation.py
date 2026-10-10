"""Check real ComfyUI generation without writing project data."""

import argparse
import asyncio
import json

import httpx

from backend.comfyui import ComfyUIClient
from backend.config import load_settings
from backend.generation import generate_images


async def run(args):
    settings = load_settings().model_copy(
        update={"image_count": args.count, "width": args.width, "height": args.height}
    )
    # Revalidate CLI overrides before sending anything.
    settings = type(settings).model_validate(settings.model_dump())
    async with httpx.AsyncClient(trust_env=False) as http:
        result = await generate_images(
            ComfyUIClient(http, settings.comfyui_url),
            settings,
            checkpoint=args.checkpoint,
            positive="landscape, mountains, blue sky",
            steps=args.steps,
            timeout=args.timeout,
        )
    print(
        json.dumps(
            {
                "parameters": result.parameters,
                "images": [
                    {
                        "position": image.position,
                        "seed": image.seed,
                        "prompt_id": image.prompt_id,
                        "bytes": len(image.data),
                    }
                    for image in result.images
                ],
            }
        )
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkpoint")
    parser.add_argument("--count", type=int, default=2)
    parser.add_argument("--width", type=int, default=512)
    parser.add_argument("--height", type=int, default=512)
    parser.add_argument("--steps", type=int, default=20)
    parser.add_argument("--timeout", type=float, default=300)
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except Exception as exc:
        print(json.dumps({"error": str(exc), "prompt_id": getattr(exc, "prompt_id", None)}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
