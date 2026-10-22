"""Import, confirm, and write task cards.

The model may propose. This module decides what is allowed to be written.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from tasks_recapture.cards import (
    SAFETY_SENTENCE,
    Card,
    Evidence,
    card_path,
    load_cards,
    new_id,
    one_line,
    render_card,
    valid_id,
    write_card,
)
from tasks_recapture.errors import ConfigError, ConflictError, RecaptureError, StoreError
from tasks_recapture.match import kind_for, match_titles, score_pair, tokenize
from tasks_recapture.store import atomic_write, directory_lock
from tasks_recapture.transcript import Transcript, load_transcript, role_for
from tasks_recapture.validate import validate_payload


@dataclass
class RunResult:
    exit_code: int = 0
    provider: str = ""
    live_api: bool = False
    origin: str = ""
    run_id: str = ""
    messages: list[str] = field(default_factory=list)
    written_ids: list[str] = field(default_factory=list)
    pending_ids: list[str] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)

    def render(self) -> str:
        lines = [
            f"provider: {self.provider or '-'}",
            f"live_api: {'true' if self.live_api else 'false'}",
            f"origin: {self.origin or '-'}",
            f"run_id: {self.run_id or '-'}",
        ]
        lines.extend(self.messages)
        if self.written_ids:
            lines.append("written: " + ", ".join(self.written_ids))
        if self.pending_ids:
            lines.append("pending: " + ", ".join(self.pending_ids))
        for item in self.rejected:
            reason = item.get("reason", "rejected")
            lines.append(f"rejected: {reason}")
        return "\n".join(lines) + "\n"


def stamp(timezone_name: str, now: str | None) -> str:
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ConfigError(f"unknown timezone: {timezone_name}") from exc
    if not now:
        return datetime.now(zone).isoformat(timespec="seconds")
    text = now.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ConfigError(" --now must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=zone)
    else:
        parsed = parsed.astimezone(zone)
    return parsed.isoformat(timespec="seconds")


def _meta(root: Path) -> Path:
    path = root / ".tasks-recapture"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _ledger_path(root: Path) -> Path:
    return _meta(root) / "ledger.json"


def _run_path(root: Path, run_id: str) -> Path:
    runs = _meta(root) / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    return runs / f"{run_id}.json"


def _read_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict) -> None:
    atomic_write(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        None,
    )


def _suggestion_key(item: dict) -> str:
    quotes = sorted(evidence["quote"] for evidence in item["evidence"])
    title = " ".join(item.get("title", "").casefold().split())
    payload = json.dumps(
        {"action": item["action"], "quotes": quotes, "title": title},
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _result_from_run(run: dict, **kwargs) -> RunResult:
    result = RunResult(
        provider=run.get("provider", ""),
        live_api=bool(run.get("live_api")),
        origin=run.get("origin", ""),
        run_id=run.get("run_id", ""),
        rejected=list(run.get("rejected") or []),
    )
    for key, value in kwargs.items():
        setattr(result, key, value)
    return result


def _index_cards(cards: list[Card]) -> dict[str, Card]:
    return {card.id: card for card in cards}


def _prepare_suggestions(accepted: list[dict], cards: list[Card]) -> list[dict]:
    prepared: list[dict] = []
    earlier: list[dict] = []
    used_ids: set[str] = set()
    by_id = _index_cards(cards)
    for item in accepted:
        hinted = item.get("existing_id") or None
        match = match_titles(item["title"], cards, hinted)
        batch_of = ""
        if item["action"] != "ignore" and match["kind"] == "none":
            for previous in earlier:
                kind = kind_for(*score_pair(item["title"], previous["title"]))
                if kind == "none":
                    continue
                batch_of = previous["suggestion_id"]
                match = {
                    "kind": "uncertain" if kind == "uncertain" else "certain",
                    "candidates": [
                        {
                            "id": previous["suggestion_id"],
                            "title": previous["title"],
                            "status": "not_started",
                            "score": 1.0 if kind == "certain" else 0.5,
                            "kind": kind,
                            "hinted": False,
                            "batch": True,
                        }
                    ],
                }
                if kind == "uncertain":
                    match["kind"] = "uncertain"
                break
        for candidate in match["candidates"]:
            card = by_id.get(candidate["id"])
            if card is not None:
                candidate["protected"] = card.protected
                candidate["status"] = card.status
        key = _suggestion_key(item)
        suggestion = dict(item)
        suggestion["key"] = key
        base_id = "sug-" + key[:12]
        suggestion_id = base_id
        suffix = 2
        while suggestion_id in used_ids:
            suggestion_id = f"{base_id}-{suffix}"
            suffix += 1
        used_ids.add(suggestion_id)
        suggestion["suggestion_id"] = suggestion_id
        suggestion["match"] = match
        suggestion["decision"] = None
        suggestion["applied"] = False
        suggestion["needs_review"] = False
        suggestion["batch_duplicate_of"] = batch_of
        if match["kind"] == "certain" and match["candidates"]:
            target = by_id.get(match["candidates"][0]["id"])
            suggestion["protected_target"] = bool(target and target.protected)
        else:
            suggestion["protected_target"] = False
        prepared.append(suggestion)
        if item["action"] != "ignore":
            earlier.append(suggestion)
    return prepared


def _preview(suggestion: dict, index: int, total: int) -> str:
    match = suggestion["match"]
    lines = [
        f"Suggestion {index}/{total} {suggestion['suggestion_id']} "
        f"action={suggestion['action']} match={match['kind']}",
        f"title: {suggestion['title']}",
        f"why: {suggestion['why']}",
        f"stop: {suggestion['stop']}",
        f"resume_when: {suggestion['resume_when'] or '(none)'}",
    ]
    for evidence in suggestion["evidence"]:
        lines.append(f'evidence: "{evidence["quote"]}" ({evidence["locator"]})')
    if suggestion["action"] == "ignore":
        lines.append(f"ignore_reason: {suggestion['ignore_reason']}")
    for number, candidate in enumerate(match.get("candidates") or [], start=1):
        lines.append(
            f"candidate {number}: {candidate['id']} status={candidate['status']} "
            f"score={candidate['score']} {candidate['title']}"
        )
    if suggestion.get("protected_target"):
        lines.append(
            "protected: accepting keeps status, stop, and resume condition, "
            "and appends a history note"
        )
    if match["kind"] == "uncertain":
        lines.append("uncertain: this will not be merged unless you pick a candidate or a new card")
        lines.append("choose: [n]ew card, a candidate number, [s]kip, [q]uit")
    elif suggestion["action"] == "ignore":
        lines.append("choose: [a]ccept ignore, [n]ew card, [s]kip, [q]uit")
    elif match["kind"] == "certain":
        lines.append("choose: [a]ccept update, [n]ew card, [s]kip, [q]uit")
    else:
        lines.append("choose: [a]ccept new card, [s]kip, [q]uit")
    return "\n".join(lines)


def _prompt_one(suggestion: dict, index: int, total: int, input_fn, output_fn) -> object:
    output_fn(_preview(suggestion, index, total))
    while True:
        try:
            answer = input_fn("decision> ").strip().lower()
        except EOFError:
            return "quit"
        if answer in {"q", "quit"}:
            return "quit"
        if answer in {"s", "skip"}:
            return "skip"
        match = suggestion["match"]
        if answer in {"n", "new"}:
            return {"choice": "new"}
        if answer in {"a", "accept", "y", "yes"}:
            if match["kind"] == "uncertain":
                output_fn("An uncertain match needs a candidate number or [n]ew.")
                continue
            return "accept"
        if answer.isdigit():
            number = int(answer)
            candidates = match.get("candidates") or []
            if match["kind"] == "uncertain" and 1 <= number <= len(candidates):
                return {"choice": "existing", "id": candidates[number - 1]["id"]}
        output_fn("Enter a, n, s, q, or a candidate number.")


def _explicit_decision(suggestion: dict, raw) -> object:
    match = suggestion["match"]
    if isinstance(raw, str) and raw in {"accept", "skip"}:
        if raw == "accept" and match["kind"] == "uncertain":
            raise RecaptureError(
                f"{suggestion['suggestion_id']} is an uncertain match; "
                "choose new or an existing id"
            )
        return raw
    if isinstance(raw, dict):
        choice = raw.get("choice")
        if choice == "new":
            return {"choice": "new"}
        if choice == "existing":
            target = str(raw.get("id") or "")
            allowed = {candidate["id"] for candidate in match.get("candidates") or []}
            if target not in allowed:
                raise RecaptureError(
                    f"{target or '(missing id)'} is not a candidate for "
                    f"{suggestion['suggestion_id']}"
                )
            return {"choice": "existing", "id": target}
    raise RecaptureError(f"bad decision for {suggestion['suggestion_id']}")


def _fill_decisions(
    run: dict,
    *,
    yes: bool,
    decisions: dict | None,
    input_fn,
    output_fn,
) -> str | None:
    """Return 'quit' if the person stopped early."""
    suggestions = run["suggestions"]
    if decisions:
        unknown = sorted(set(decisions) - {item["suggestion_id"] for item in suggestions})
        if unknown:
            raise RecaptureError("unknown suggestion id in decisions: " + ", ".join(unknown))
    for index, suggestion in enumerate(suggestions, start=1):
        if suggestion.get("applied") or suggestion.get("decision") not in (None, ""):
            continue
        if decisions and suggestion["suggestion_id"] in decisions:
            suggestion["decision"] = _explicit_decision(
                suggestion, decisions[suggestion["suggestion_id"]]
            )
            suggestion["needs_review"] = False
            continue
        if yes and not suggestion.get("needs_review"):
            if suggestion["match"]["kind"] == "uncertain":
                continue
            suggestion["decision"] = "accept"
            continue
        if input_fn is None:
            continue
        choice = _prompt_one(suggestion, index, len(suggestions), input_fn, output_fn)
        if choice == "quit":
            return "quit"
        suggestion["decision"] = choice
    return None


def _interpret(suggestion: dict) -> tuple[str, str | None]:
    decision = suggestion.get("decision")
    if decision in (None, ""):
        return "pending", None
    if decision == "skip":
        return "skip", None
    match = suggestion["match"]
    if suggestion["action"] == "ignore" and decision == "accept":
        return "ignore", None
    if isinstance(decision, dict) and decision.get("choice") == "new":
        return "create", None
    if isinstance(decision, dict) and decision.get("choice") == "existing":
        return "update", decision["id"]
    if decision == "accept":
        if match["kind"] == "uncertain":
            return "pending", None
        if match["kind"] == "certain":
            return "update", match["candidates"][0]["id"]
        return "create", None
    return "pending", None


def _initial_status(suggestion: dict) -> tuple[str, str]:
    proposed = suggestion.get("proposed_status") or "not_started"
    resume = (suggestion.get("resume_when") or "").strip()
    if proposed == "paused" and resume:
        return "paused", ""
    note = ""
    if proposed not in {"not_started", "paused"} or (proposed == "paused" and not resume):
        note = (
            f"Model proposed status {proposed}; stored as not_started. "
            "Import does not start or finish work."
        )
    return "not_started", note


def _origin_lines(transcript: Transcript, suggestion: dict, origin: str) -> list[str]:
    quote = suggestion["evidence"][0]["quote"]
    role = role_for(transcript, quote)
    locator = suggestion["evidence"][0]["locator"]
    return [
        f"label: {transcript.label}",
        f"fingerprint: sha256:{transcript.fingerprint}",
        f"role: {role}",
        f"locator: {locator}",
        f"provider: {origin}",
    ]


def _source_line(transcript: Transcript, suggestion: dict) -> str:
    quote = suggestion["evidence"][0]["quote"]
    return one_line(
        f"{transcript.label} sha256:{transcript.fingerprint} "
        f"{suggestion['evidence'][0]['locator']} role:{role_for(transcript, quote)}"
    )


def _append_unique(items: list[str], extra: list[str]) -> None:
    for item in extra:
        if item and item not in items:
            items.append(item)


def _create_card(
    root: Path,
    cards: list[Card],
    suggestion: dict,
    transcript: Transcript,
    origin: str,
    when: str,
) -> Card:
    status, note = _initial_status(suggestion)
    identity = new_id({card.id for card in cards})
    history = [
        one_line(
            f"{when} imported from {transcript.label} as {status} ({origin}). {SAFETY_SENTENCE}"
        )
    ]
    if note:
        history.append(one_line(f"{when} {note} {SAFETY_SENTENCE}"))
    card = Card(
        status=status,
        id=identity,
        manual=False,
        authorization="record_only",
        owner="unspecified",
        actor="unspecified",
        updated=when,
        stop=suggestion["stop"] or "No stop point was recorded.",
        resume_when=suggestion["resume_when"],
        source=_source_line(transcript, suggestion),
        suggestion_origin=origin,
        title=suggestion["title"],
        why=suggestion["why"] or "The transcript contained unfinished work.",
        where_stopped=suggestion["stop"] or "No stop point was recorded.",
        evidence=[
            Evidence(item["quote"], item["locator"]) for item in suggestion["evidence"]
        ],
        origin_lines=_origin_lines(transcript, suggestion, origin),
        history=history,
    )
    card.path = card_path(root, card)
    if card.path.exists():
        card.path = card.path.with_name(card.path.stem + "-2.md")
    write_card(root, card, None)
    return card


def _history_note(when: str, transcript: Transcript, origin: str, text: str) -> str:
    return one_line(f"{when} {text} Source {transcript.label} ({origin}). {SAFETY_SENTENCE}")


def _update_card(
    root: Path,
    card: Card,
    suggestion: dict,
    transcript: Transcript,
    origin: str,
    when: str,
    expected_hash: str,
) -> Card:
    # Re-read so the hash check and the merge use the same bytes.
    current = load_cards(root)
    fresh = next((item for item in current if item.id == card.id), None)
    if fresh is None or fresh.path is None:
        raise ConflictError(f"{card.id} is missing; nothing was written")
    if fresh.content_hash != expected_hash:
        raise ConflictError(
            f"{card.id} changed after it was read; the new contents were kept"
        )
    if fresh.protected:
        _append_unique(
            fresh.history,
            [
                _history_note(
                    when,
                    transcript,
                    origin,
                    f"an import offered an update titled {suggestion['title']!r}. "
                    f"Status stayed {fresh.status}; stop and resume condition were kept "
                    "because the card is done, paused, or manually set.",
                )
            ],
        )
    else:
        if suggestion.get("stop"):
            fresh.stop = suggestion["stop"]
            fresh.where_stopped = suggestion["stop"]
        if suggestion.get("resume_when"):
            fresh.resume_when = suggestion["resume_when"]
        if suggestion.get("why") and suggestion["why"] not in fresh.why:
            fresh.why = (fresh.why + "\n\n" + suggestion["why"]).strip()
        known = {item.quote for item in fresh.evidence}
        for item in suggestion["evidence"]:
            if item["quote"] not in known:
                fresh.evidence.append(Evidence(item["quote"], item["locator"]))
        fresh.updated = when
        fresh.source = _source_line(transcript, suggestion)
        fresh.suggestion_origin = origin
        _append_unique(fresh.origin_lines, _origin_lines(transcript, suggestion, origin))
        _append_unique(
            fresh.history,
            [
                _history_note(
                    when,
                    transcript,
                    origin,
                    f"updated the record for {fresh.title!r}. Status stayed {fresh.status}.",
                )
            ],
        )
    fresh.authorization = "record_only"
    write_card(root, fresh, expected_hash)
    return fresh


def _target_card(cards: list[Card], target: str, created: dict[str, str]) -> Card | None:
    if target in created:
        target = created[target]
    if not valid_id(target):
        return None
    return next((card for card in cards if card.id == target), None)


def _apply(root: Path, run: dict, transcript: Transcript, when: str) -> RunResult:
    result = _result_from_run(run)
    for index, suggestion in enumerate(run["suggestions"], start=1):
        if not suggestion.get("applied"):
            result.messages.append(_preview(suggestion, index, len(run["suggestions"])))
    cards = load_cards(root)
    created: dict[str, str] = {}
    pending: list[str] = []
    for suggestion in run["suggestions"]:
        if suggestion.get("applied"):
            if suggestion.get("card_id"):
                result.written_ids.append(suggestion["card_id"])
            continue
        action, target = _interpret(suggestion)
        if action == "pending":
            pending.append(suggestion["suggestion_id"])
            continue
        if action == "skip":
            suggestion["applied"] = True
            suggestion["outcome"] = "skipped"
            result.messages.append(f"skipped {suggestion['suggestion_id']}")
            continue
        if action == "ignore":
            suggestion["applied"] = True
            suggestion["outcome"] = "ignored"
            result.messages.append(
                f"ignored {suggestion['suggestion_id']}: {suggestion['ignore_reason']}"
            )
            continue
        try:
            if action == "update":
                known = {
                    item["suggestion_id"]: item["card_id"]
                    for item in run["suggestions"]
                    if item.get("card_id")
                }
                known.update(created)
                if target in known or (target and not valid_id(target)):
                    mapped = known.get(target or "")
                    if mapped is None and suggestion.get("batch_duplicate_of"):
                        mapped = known.get(suggestion["batch_duplicate_of"])
                    if mapped is None:
                        action = "create"
                        target = None
                    else:
                        target = mapped
                if action == "update":
                    cards = load_cards(root)
                    card = _target_card(cards, target or "", created)
                    if card is None:
                        raise ConflictError(f"{target} is not in the task library")
                    expected = run.get("card_hashes", {}).get(card.id, card.content_hash)
                    updated = _update_card(
                        root, card, suggestion, transcript, run["origin"], when, expected
                    )
                    suggestion["card_id"] = updated.id
                    run.setdefault("card_hashes", {})[updated.id] = updated.content_hash
            if action == "create":
                created_card = _create_card(
                    root, load_cards(root), suggestion, transcript, run["origin"], when
                )
                created[suggestion["suggestion_id"]] = created_card.id
                suggestion["card_id"] = created_card.id
                run.setdefault("card_hashes", {})[created_card.id] = created_card.content_hash
                result.messages.append(
                    f"created {created_card.id} status={created_card.status} {created_card.title}"
                )
            elif action == "update":
                result.messages.append(
                    f"updated {suggestion['card_id']} from {suggestion['suggestion_id']}"
                )
            suggestion["applied"] = True
            suggestion["outcome"] = action
            if suggestion.get("card_id"):
                result.written_ids.append(suggestion["card_id"])
        except ConflictError as exc:
            suggestion["decision"] = None
            suggestion["needs_review"] = True
            suggestion["applied"] = False
            pending.append(suggestion["suggestion_id"])
            result.messages.append(f"conflict {suggestion['suggestion_id']}: {exc}")
            cards = load_cards(root)
            if target and valid_id(str(target)):
                fresh = next((card for card in cards if card.id == target), None)
                if fresh is not None:
                    run.setdefault("card_hashes", {})[fresh.id] = fresh.content_hash
    result.pending_ids = pending
    unresolved = [item["suggestion_id"] for item in run["suggestions"] if not item.get("applied")]
    result.pending_ids = unresolved
    if unresolved:
        run["state"] = "awaiting_confirm"
        result.exit_code = 2
        result.messages.append(
            "pending human decision; nothing uncertain was merged. "
            "Resume this run id after choosing."
        )
    else:
        run["state"] = "complete"
        result.exit_code = 0
        result.messages.append("verified writes and recorded this transcript as processed")
    return result


def _save_progress(root: Path, run: dict, transcript: Transcript) -> None:
    _write_json(_run_path(root, run["run_id"]), run)
    ledger = _read_json(_ledger_path(root), {"version": 1, "sources": {}})
    ledger["version"] = 1
    sources = ledger.setdefault("sources", {})
    sources[transcript.fingerprint] = {
        "label": transcript.label,
        "run_id": run["run_id"],
        "state": run["state"],
        "card_ids": sorted(
            {
                item["card_id"]
                for item in run["suggestions"]
                if item.get("card_id")
            }
        ),
    }
    _write_json(_ledger_path(root), ledger)


def _packet(transcript: Transcript, cards: list[Card], timezone_name: str) -> dict:
    return {
        "timezone": timezone_name,
        "transcript_label": transcript.label,
        "transcript_text": transcript.text,
        "messages": [
            {
                "role": message.role,
                "locator": f"lines {message.start_line}-{message.end_line}",
                "text": message.text,
            }
            for message in transcript.messages
        ],
        "cards": [
            {
                "id": card.id,
                "title": card.title,
                "status": card.status,
                "stop": card.stop,
                "resume_when": card.resume_when,
                "manual": card.manual,
            }
            for card in cards
        ],
    }


def _new_run(root: Path, transcript: Transcript, payload: dict, cards: list[Card], when: str) -> dict:
    provider = payload.get("provider") or ""
    origin = payload.get("origin") or ""
    live = bool(payload.get("live_api"))
    if provider == "mock":
        live = False
    accepted, rejected = validate_payload(payload, transcript)
    suggestions = _prepare_suggestions(accepted, cards)
    return {
        "version": 1,
        "run_id": "run-" + uuid.uuid4().hex[:12],
        "state": "awaiting_confirm",
        "provider": provider,
        "live_api": live,
        "origin": origin,
        "fingerprint": transcript.fingerprint,
        "label": transcript.label,
        "created_at": when,
        "suggestions": suggestions,
        "rejected": rejected,
        "card_hashes": {card.id: card.content_hash for card in cards},
        "transcript_text": transcript.text,
    }


def _continue(
    root: Path,
    run: dict,
    transcript: Transcript,
    *,
    yes: bool,
    decisions: dict | None,
    stop_after: str | None,
    when: str,
    input_fn,
    output_fn,
) -> RunResult:
    if stop_after == "propose" and run["state"] == "awaiting_confirm" and not any(
        item.get("decision") for item in run["suggestions"]
    ):
        # Used when the caller just built the run and wants to stop before confirm.
        if stop_after == "propose" and run.get("_stop_propose"):
            result = _result_from_run(run, exit_code=3)
            result.pending_ids = [item["suggestion_id"] for item in run["suggestions"]]
            result.messages.append("checkpoint propose; no cards were written")
            for suggestion in run["suggestions"]:
                result.messages.append(_preview(suggestion, 1, 1))
            return result

    if run["state"] == "complete":
        result = _result_from_run(run, exit_code=0)
        result.written_ids = sorted(
            {item["card_id"] for item in run["suggestions"] if item.get("card_id")}
        )
        result.messages.append("already processed; no new card was written")
        return result

    if run["state"] == "ready_to_write":
        result = _apply(root, run, transcript, when)
        _save_progress(root, run, transcript)
        return result

    quit_now = _fill_decisions(
        run, yes=yes, decisions=decisions, input_fn=input_fn, output_fn=output_fn
    )
    if stop_after == "before-write":
        run["state"] = "ready_to_write"
        _save_progress(root, run, transcript)
        result = _result_from_run(run, exit_code=3)
        result.pending_ids = [
            item["suggestion_id"] for item in run["suggestions"] if not item.get("decision")
        ]
        result.messages.append("checkpoint before-write; decisions are saved and no cards were written")
        return result
    if quit_now:
        run["state"] = "awaiting_confirm"
        _save_progress(root, run, transcript)
        result = _result_from_run(run, exit_code=2)
        result.pending_ids = [
            item["suggestion_id"] for item in run["suggestions"] if not item.get("applied")
        ]
        result.messages.append("stopped before every suggestion had a decision; resume this run id")
        return result
    result = _apply(root, run, transcript, when)
    _save_progress(root, run, transcript)
    return result


def import_transcript(
    transcript_path: Path,
    *,
    tasks_dir: Path,
    timezone_name: str = "UTC",
    provider,
    now: str | None = None,
    yes: bool = False,
    decisions: dict | None = None,
    stop_after: str | None = None,
    reanalyze: bool = False,
    input_fn=None,
    output_fn=None,
) -> RunResult:
    output_fn = output_fn or (lambda _text: None)
    when = stamp(timezone_name, now)
    transcript = load_transcript(transcript_path)
    tasks_dir.mkdir(parents=True, exist_ok=True)
    with directory_lock(tasks_dir):
        ledger = _read_json(_ledger_path(tasks_dir), {"version": 1, "sources": {}})
        source = (ledger.get("sources") or {}).get(transcript.fingerprint)
        if source and source.get("state") == "complete" and not reanalyze:
            run = _read_json(_run_path(tasks_dir, source["run_id"]), {})
            result = _result_from_run(run or {"run_id": source.get("run_id", "")}, exit_code=0)
            result.live_api = False if (run or {}).get("provider") == "mock" else result.live_api
            result.messages.append("already processed; no new card was written")
            result.written_ids = list(source.get("card_ids") or [])
            return result
        if source and source.get("state") != "complete" and reanalyze:
            raise RecaptureError("finish or resume the open run before --reanalyze")
        if source and source.get("state") != "complete" and not reanalyze:
            run = _read_json(_run_path(tasks_dir, source["run_id"]), {})
            if run.get("fingerprint") != transcript.fingerprint:
                raise StoreError("saved run does not match this transcript")
            run["_stop_propose"] = False
            return _continue(
                tasks_dir,
                run,
                transcript,
                yes=yes,
                decisions=decisions,
                stop_after=stop_after if stop_after != "propose" else None,
                when=when,
                input_fn=input_fn,
                output_fn=output_fn,
            )
        cards = load_cards(tasks_dir)
        payload = provider.propose(
            _packet(transcript, cards, timezone_name)
        )
        if not isinstance(payload, dict):
            raise RecaptureError("provider returned a non-object")
        run = _new_run(tasks_dir, transcript, payload, cards, when)
        run["_stop_propose"] = stop_after == "propose"
        _save_progress(tasks_dir, run, transcript)
        if stop_after == "propose":
            return _continue(
                tasks_dir,
                run,
                transcript,
                yes=False,
                decisions=None,
                stop_after="propose",
                when=when,
                input_fn=None,
                output_fn=output_fn,
            )
        return _continue(
            tasks_dir,
            run,
            transcript,
            yes=yes,
            decisions=decisions,
            stop_after=stop_after,
            when=when,
            input_fn=input_fn,
            output_fn=output_fn,
        )


def resume_run(
    tasks_dir: Path,
    *,
    run_id: str | None = None,
    timezone_name: str = "UTC",
    now: str | None = None,
    yes: bool = False,
    decisions: dict | None = None,
    input_fn=None,
    output_fn=None,
) -> RunResult:
    output_fn = output_fn or (lambda _text: None)
    when = stamp(timezone_name, now)
    tasks_dir.mkdir(parents=True, exist_ok=True)
    with directory_lock(tasks_dir):
        runs_dir = _meta(tasks_dir) / "runs"
        if run_id is None:
            found = sorted(runs_dir.glob("run-*.json")) if runs_dir.exists() else []
            open_runs = []
            for path in found:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if payload.get("state") != "complete":
                    open_runs.append(payload)
            if len(open_runs) != 1:
                raise RecaptureError(
                    f"expected one open run to resume, found {len(open_runs)}; pass --run-id"
                )
            run = open_runs[0]
        else:
            path = _run_path(tasks_dir, run_id)
            if not path.exists():
                raise RecaptureError(f"no saved run {run_id}")
            run = json.loads(path.read_text(encoding="utf-8"))
        transcript = Transcript(
            label=run.get("label") or "transcript",
            fingerprint=run["fingerprint"],
            text=run.get("transcript_text") or "",
            messages=(),
        )
        # Role lookup needs messages. Reparse the saved normalized text.
        from tasks_recapture.transcript import parse_messages

        transcript = Transcript(
            label=transcript.label,
            fingerprint=transcript.fingerprint,
            text=transcript.text,
            messages=parse_messages(transcript.text),
        )
        run["_stop_propose"] = False
        return _continue(
            tasks_dir,
            run,
            transcript,
            yes=yes,
            decisions=decisions,
            stop_after=None,
            when=when,
            input_fn=input_fn,
            output_fn=output_fn,
        )


def mark_status(
    tasks_dir: Path,
    card_id: str,
    status: str,
    *,
    timezone_name: str = "UTC",
    now: str | None = None,
) -> RunResult:
    from tasks_recapture.cards import STATUSES

    if status not in STATUSES:
        raise RecaptureError(f"status must be one of: {', '.join(STATUSES)}")
    if not valid_id(card_id):
        raise RecaptureError("not a task id")
    when = stamp(timezone_name, now)
    tasks_dir.mkdir(parents=True, exist_ok=True)
    with directory_lock(tasks_dir):
        cards = load_cards(tasks_dir)
        card = next((item for item in cards if item.id == card_id), None)
        if card is None:
            raise RecaptureError(f"{card_id} was not found")
        previous = card.status
        if previous == status and card.manual:
            result = RunResult(exit_code=0, messages=[f"{card_id} already {status} and manual"])
            return result
        expected = card.content_hash
        card.status = status
        card.manual = True
        card.authorization = "record_only"
        card.updated = when
        _append_unique(
            card.history,
            [
                one_line(
                    f"{when} a person set the status from {previous} to {status}. "
                    f"Manual protection is on. {SAFETY_SENTENCE}"
                )
            ],
        )
        write_card(tasks_dir, card, expected)
        verified = next(item for item in load_cards(tasks_dir) if item.id == card_id)
        if verified.status != status or not verified.manual:
            raise StoreError("read-back verification failed after mark")
        return RunResult(
            exit_code=0,
            written_ids=[card_id],
            messages=[
                f"marked {card_id} {previous} -> {status}. "
                "This does not authorize anyone to execute the task."
            ],
        )


def review_cards(tasks_dir: Path, transcript_path: Path | None = None) -> list[dict]:
    cards = load_cards(tasks_dir) if tasks_dir.exists() else []
    text = ""
    if transcript_path is not None:
        text = load_transcript(transcript_path).text
    hints = []
    for card in cards:
        if card.status == "done" or not card.resume_when.strip():
            continue
        if not text:
            hints.append(
                {
                    "id": card.id,
                    "title": card.title,
                    "status": card.status,
                    "protected": card.protected,
                    "resume_when": card.resume_when,
                    "status_unchanged": True,
                    "message": "Recorded resume condition. Status was not changed.",
                }
            )
            continue
        needed = tokenize(card.resume_when)
        found = needed & tokenize(text)
        if needed and len(found) >= 2 and len(found) / len(needed) >= 0.6:
            hints.append(
                {
                    "id": card.id,
                    "title": card.title,
                    "status": card.status,
                    "protected": card.protected,
                    "resume_when": card.resume_when,
                    "overlap": sorted(found),
                    "status_unchanged": True,
                    "message": (
                        "Resume condition may be satisfied. Status was not changed "
                        "and paused, done, or manual cards were not reopened."
                    ),
                }
            )
    return hints


def render_review(hints: list[dict]) -> str:
    if not hints:
        return "review: no resume condition to report\n"
    lines = ["review: status was not changed"]
    for hint in hints:
        lines.append(
            f"{hint['id']} status={hint['status']} protected={'true' if hint['protected'] else 'false'}"
        )
        lines.append(f"resume_when: {hint['resume_when']}")
        lines.append(hint["message"])
    return "\n".join(lines) + "\n"


def render_list(cards: list[Card]) -> str:
    order = {status: index for index, status in enumerate(
        ("not_started", "in_progress", "paused", "done")
    )}
    lines = []
    for card in sorted(cards, key=lambda item: (order.get(item.status, 9), item.title)):
        lines.append(
            f"{card.id}  {card.status}  manual={'true' if card.manual else 'false'}  {card.title}"
        )
        lines.append(f"  stop: {one_line(card.stop)}")
        if card.resume_when:
            lines.append(f"  resume_when: {one_line(card.resume_when)}")
    if not lines:
        return "no task cards\n"
    return "\n".join(lines) + "\n"
