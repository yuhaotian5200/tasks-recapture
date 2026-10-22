"""Shared helpers for synthetic fixtures. Nothing here is a live model call."""

from __future__ import annotations

import tempfile
from pathlib import Path

from tasks_recapture.flow import import_transcript
from tasks_recapture.model import FixedMockProvider


def mock_provider(suggestions: list[dict], **extra) -> FixedMockProvider:
    payload = {
        "provider": "openai-compatible",
        "live_api": True,
        "origin": "live-api",
        "suggestions": suggestions,
    }
    payload.update(extra)
    return FixedMockProvider(payload)


def suggestion(
    action: str,
    quote: str,
    *,
    title: str = "",
    why: str = "It was left unfinished.",
    stop: str = "It has not been started.",
    resume_when: str = "",
    proposed_status: str = "not_started",
    existing_id: str | None = None,
    ignore_reason: str = "",
    **extra,
) -> dict:
    item = {
        "action": action,
        "title": title,
        "why": why,
        "stop": stop,
        "resume_when": resume_when,
        "proposed_status": proposed_status,
        "existing_id": existing_id,
        "ignore_reason": ignore_reason,
        "evidence": [{"quote": quote}],
    }
    item.update(extra)
    return item


def write_text(directory: Path, name: str, body: str) -> Path:
    path = directory / name
    path.write_text(body, encoding="utf-8")
    return path


def temporary_dir():
    return tempfile.TemporaryDirectory()


def run_import(path: Path, tasks: Path, provider, **kwargs):
    kwargs.setdefault("timezone_name", "UTC")
    kwargs.setdefault("now", "2026-10-22T12:00:00")
    return import_transcript(path, tasks_dir=tasks, provider=provider, **kwargs)
