"""Run a local API-format workflow and report success/failure without saving DB rows."""

import argparse
import asyncio
import json
from pathlib import Path

import httpx

from backend.comfyui import ComfyUIClient, ComfyUIError, load_workflow
from backend.config import load_settings


async def run(args):
    workflow = load_workflow(args.workflow)
    async with httpx.AsyncClient(trust_env=False) as http:
        result = await ComfyUIClient(http, load_settings().comfyui_url).execute(
            workflow, timeout=args.timeout
        )
    print(
        json.dumps({"prompt_id": result.prompt_id, "outputs": result.outputs}, ensure_ascii=False)
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workflow", type=Path)
    parser.add_argument("--timeout", type=float, default=300)
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except (ComfyUIError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "error": str(exc),
                    "prompt_id": getattr(exc, "prompt_id", None),
                    "details": getattr(exc, "details", None),
                },
                ensure_ascii=False,
            )
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
