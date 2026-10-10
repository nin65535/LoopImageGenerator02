"""Verify real generation, tagging and atomic persistence in isolated temporary storage."""

import argparse
import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx

from backend.comfyui import ComfyUIClient
from backend.config import load_settings
from backend.database import Database
from backend.generation import generate_images
from backend.generation_storage import tag_and_save_generation


async def run(args):
    with TemporaryDirectory(prefix="loop-generation-check-") as directory:
        storage = Path(directory)
        settings = load_settings().model_copy(
            update={"storage_dir": storage, "image_count": args.count, "width": 256, "height": 384}
        )
        settings = type(settings).model_validate(settings.model_dump())
        database = Database(settings.database_path)
        database.initialize()
        with database.transaction() as connection:
            project_id = connection.execute(
                "INSERT INTO projects (name, initial_image_path) VALUES ('isolated check', '')"
            ).lastrowid
        async with httpx.AsyncClient(trust_env=False) as http:
            client = ComfyUIClient(http, settings.comfyui_url)
            result = await generate_images(
                client,
                settings,
                checkpoint=args.checkpoint,
                positive="landscape, mountains, blue sky",
                steps=4,
            )
            generation_id = await tag_and_save_generation(
                client, database, storage, project_id, result
            )
        # Reopen to verify committed data and files, rather than in-memory results.
        with Database(settings.database_path).connect() as connection:
            generation = connection.execute(
                "SELECT * FROM generations WHERE id = ?", (generation_id,)
            ).fetchone()
            rows = connection.execute(
                "SELECT * FROM images WHERE generation_id = ? ORDER BY position", (generation_id,)
            ).fetchall()
        assert len(rows) == args.count
        assert json.loads(generation["parameters_json"]) == result.parameters
        for row, image in zip(rows, result.images, strict=True):
            assert row["position"] == image.position and row["seed"] == image.seed
            assert (storage / row["file_path"]).read_bytes() == image.data
            assert isinstance(json.loads(row["tags_json"]), dict)
        assert not list((storage / "staging").iterdir())
        print(
            json.dumps(
                {
                    "saved_images": len(rows),
                    "tag_counts": [len(json.loads(row["tags_json"])) for row in rows],
                    "parameters": result.parameters,
                }
            )
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkpoint")
    parser.add_argument("--count", type=int, default=2)
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except Exception as exc:
        print(json.dumps({"error": str(exc), "prompt_id": getattr(exc, "prompt_id", None)}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
