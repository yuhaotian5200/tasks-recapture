"""Check model suggestions. Transcript quotes must be exact source substrings."""

from __future__ import annotations

from tasks_recapture.cards import STATUSES, valid_id
from tasks_recapture.transcript import Transcript, locator_for

DANGEROUS_KEYS = {
    "command",
    "commands",
    "shell",
    "tool",
    "tools",
    "execute",
    "exec",
    "system",
    "api_key",
    "apikey",
    "authorization",
    "token",
    "secret",
    "password",
    "path",
    "write_path",
    "status",
    "eval",
    "subprocess",
}

ALLOWED_KEYS = {
    "action",
    "title",
    "why",
    "stop",
    "resume_when",
    "proposed_status",
    "existing_id",
    "evidence",
    "ignore_reason",
}

MAX_SUGGESTIONS = 30


def _limit(value: object, max_len: int) -> str:
    text = "" if value is None else str(value)
    text = text.strip()
    if len(text) > max_len:
        return text[:max_len].rstrip()
    return text


def validate_payload(payload: dict, transcript: Transcript) -> tuple[list[dict], list[dict]]:
    """Return accepted suggestions and rejection records.

    Unknown top-level instructions are ignored. A suggestion that carries a
    control key such as `command` is rejected as a whole.
    """
    if not isinstance(payload, dict):
        return [], [{"index": None, "reason": "model output is not a JSON object"}]
    suggestions = payload.get("suggestions")
    if not isinstance(suggestions, list):
        return [], [{"index": None, "reason": "model output has no suggestions list"}]

    accepted: list[dict] = []
    rejected: list[dict] = []
    warnings: list[str] = []
    for key in payload:
        if key in DANGEROUS_KEYS:
            warnings.append(f"ignored top-level field {key}")
    if len(suggestions) > MAX_SUGGESTIONS:
        rejected.append(
            {
                "index": None,
                "reason": f"ignored suggestions past the limit of {MAX_SUGGESTIONS}",
            }
        )
        suggestions = suggestions[:MAX_SUGGESTIONS]

    for index, raw in enumerate(suggestions):
        if not isinstance(raw, dict):
            rejected.append({"index": index, "reason": "suggestion is not an object"})
            continue
        dangerous = sorted(set(raw) & DANGEROUS_KEYS)
        if dangerous:
            rejected.append(
                {
                    "index": index,
                    "reason": "suggestion includes control fields and was rejected: "
                    + ", ".join(dangerous),
                }
            )
            continue
        action = str(raw.get("action", "")).strip().lower()
        if action not in {"add", "update", "ignore"}:
            rejected.append(
                {
                    "index": index,
                    "reason": f"unsupported action {action or '(empty)'}",
                }
            )
            continue
        evidence_raw = raw.get("evidence")
        if not isinstance(evidence_raw, list) or not evidence_raw:
            rejected.append({"index": index, "reason": "suggestion has no evidence quotes"})
            continue
        quotes: list[dict] = []
        quote_error = ""
        for item in evidence_raw:
            if isinstance(item, str):
                quote = item.strip()
            elif isinstance(item, dict):
                quote = str(item.get("quote", "")).strip()
            else:
                quote_error = "evidence item is not a quote"
                break
            if len(quote) < 8:
                quote_error = "evidence quote is shorter than 8 characters"
                break
            if quote not in transcript.text:
                quote_error = "evidence quote is not an exact substring of the transcript"
                break
            quotes.append({"quote": quote, "locator": locator_for(transcript.text, quote)})
        if quote_error:
            rejected.append({"index": index, "reason": quote_error})
            continue
        title = _limit(raw.get("title"), 200)
        if action in {"add", "update"} and not title:
            rejected.append({"index": index, "reason": "add and update need a title"})
            continue
        proposed = str(raw.get("proposed_status") or "not_started").strip().lower()
        if proposed not in STATUSES:
            proposed = "not_started"
        hinted = str(raw.get("existing_id") or "").strip()
        if hinted and not valid_id(hinted):
            hinted = ""
            rejected_hint = True
        else:
            rejected_hint = False
        cleaned = {
            "action": action,
            "title": title,
            "why": _limit(raw.get("why"), 2000),
            "stop": _limit(raw.get("stop"), 1000),
            "resume_when": _limit(raw.get("resume_when"), 1000),
            "proposed_status": proposed,
            "existing_id": hinted,
            "ignore_reason": _limit(raw.get("ignore_reason"), 1000),
            "evidence": quotes,
            "hint_dropped": rejected_hint,
        }
        if action == "ignore" and not cleaned["ignore_reason"]:
            cleaned["ignore_reason"] = "The model marked this passage as not an open task."
        accepted.append(cleaned)
    if warnings:
        rejected.append({"index": None, "reason": "; ".join(warnings)})
    return accepted, rejected
