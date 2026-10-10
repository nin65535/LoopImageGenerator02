"""ComfyUI API-format workflow execution without database writes."""

import asyncio
import json
import math
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

import httpx


class ComfyUIError(Exception):
    """Transport, protocol, validation or execution failure with diagnostic context."""

    def __init__(self, message, *, prompt_id=None, details=None):
        super().__init__(message)
        self.prompt_id = prompt_id
        self.details = details


class ComfyUITimeout(ComfyUIError):
    """Waiting stopped; the remote prompt may still be queued or running."""


def validate_workflow(workflow: object) -> dict:
    if not isinstance(workflow, dict) or not workflow:
        raise ComfyUIError("Workflow must be a non-empty API-format node object")
    for node_id, node in workflow.items():
        if (
            not isinstance(node_id, str)
            or not node_id
            or not isinstance(node, dict)
            or not isinstance(node.get("class_type"), str)
            or not node["class_type"].strip()
            or not isinstance(node.get("inputs"), dict)
        ):
            raise ComfyUIError("Use a ComfyUI API export, not the editor workflow format")
    try:
        json.dumps(workflow, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ComfyUIError("Workflow must contain valid JSON values") from exc
    return workflow


def load_workflow(path: Path) -> dict:
    try:
        workflow = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise ComfyUIError(f"Cannot read workflow: {path}") from exc
    return validate_workflow(workflow)


@dataclass(frozen=True)
class WorkflowResult:
    prompt_id: str
    outputs: dict
    history: dict


class ComfyUIClient:
    """Use a caller-owned AsyncClient so lifespan and cancellation remain explicit."""

    def __init__(self, client: httpx.AsyncClient, url: str):
        self.client = client
        self.url = url.rstrip("/")

    async def _request(self, method, path, timeout, *, prompt_id=None, payload=None, **kwargs):
        try:
            response = await self.client.request(
                method, self.url + path, json=payload, timeout=timeout, **kwargs
            )
        except httpx.TimeoutException as exc:
            raise ComfyUITimeout("ComfyUI request timed out", prompt_id=prompt_id) from exc
        except httpx.RequestError as exc:
            raise ComfyUIError("Cannot connect to ComfyUI", prompt_id=prompt_id) from exc
        try:
            data = response.json()
        except ValueError as exc:
            raise ComfyUIError(
                "ComfyUI returned invalid JSON",
                prompt_id=prompt_id,
                details={"status_code": response.status_code},
            ) from exc
        if not response.is_success:
            raise ComfyUIError(
                f"ComfyUI HTTP {response.status_code}", prompt_id=prompt_id, details=data
            )
        if not isinstance(data, dict):
            raise ComfyUIError("ComfyUI response must be an object", prompt_id=prompt_id)
        return data

    async def execute(self, workflow: dict, *, timeout=300.0, poll_interval=0.5):
        validate_workflow(workflow)
        for value in (timeout, poll_interval):
            if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
                raise ValueError("Timeout and poll interval must be finite and positive")
        prompt_id = None
        try:
            async with asyncio.timeout(timeout):
                submitted = await self._request(
                    "POST",
                    "/prompt",
                    min(timeout, 30),
                    payload={"prompt": workflow, "client_id": str(uuid4())},
                )
                prompt_id = submitted.get("prompt_id")
                if not isinstance(prompt_id, str) or not prompt_id:
                    raise ComfyUIError("ComfyUI did not return prompt_id", details=submitted)
                while True:
                    history = await self._request(
                        "GET",
                        "/history/" + quote(prompt_id, safe=""),
                        min(timeout, 30),
                        prompt_id=prompt_id,
                    )
                    if prompt_id in history:
                        record = history[prompt_id]
                        if not isinstance(record, dict) or not isinstance(
                            record.get("status"), dict
                        ):
                            raise ComfyUIError("Invalid history status", prompt_id=prompt_id)
                        status = record["status"]
                        messages = status.get("messages", [])
                        if not isinstance(messages, list):
                            raise ComfyUIError("Invalid history messages", prompt_id=prompt_id)
                        failed = any(
                            isinstance(m, (list, tuple))
                            and m
                            and isinstance(m[0], str)
                            and m[0] in {"execution_error", "execution_interrupted"}
                            for m in messages
                        )
                        if status.get("status_str") == "error" or failed:
                            raise ComfyUIError(
                                "ComfyUI workflow failed", prompt_id=prompt_id, details=record
                            )
                        if status.get("completed") is True:
                            if status.get("status_str") != "success" or not isinstance(
                                record.get("outputs"), dict
                            ):
                                raise ComfyUIError("Invalid completed history", prompt_id=prompt_id)
                            return WorkflowResult(prompt_id, record["outputs"], record)
                    await asyncio.sleep(poll_interval)
        except TimeoutError as exc:
            raise ComfyUITimeout(
                "ComfyUI workflow timed out; remote execution may continue", prompt_id=prompt_id
            ) from exc
