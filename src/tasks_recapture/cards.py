"""Markdown task cards. The card is a record, not permission to do the work."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from tasks_recapture.errors import StoreError, ValidationError
from tasks_recapture.store import atomic_write, resolve_inside, sha256_text

STATUSES = ("not_started", "in_progress", "paused", "done")
PROTECTED_STATUSES = frozenset({"paused", "done"})
SAFETY_SENTENCE = (
    "Saving or updating this card does not authorize anyone to execute the task."
)

_FIELD = re.compile(r"^\*\*([A-Za-z0-9_]+):\*\*\s*(.*)$")
_TITLE = re.compile(r"^#\s+(.+?)\s*$")
_ID = re.compile(r"^task-[0-9a-f]{12}$")

STANDARD_SECTIONS = (
    "Why this was kept",
    "Where it stopped",
    "Resume condition",
    "Evidence",
    "Origin",
    "History",
)


@dataclass
class Evidence:
    quote: str
    locator: str = ""


@dataclass
class Card:
    status: str
    id: str
    manual: bool
    authorization: str
    owner: str
    actor: str
    updated: str
    stop: str
    resume_when: str
    source: str
    suggestion_origin: str
    title: str
    why: str
    where_stopped: str
    evidence: list[Evidence] = field(default_factory=list)
    origin_lines: list[str] = field(default_factory=list)
    history: list[str] = field(default_factory=list)
    extra_sections: dict[str, str] = field(default_factory=dict)
    path: Path | None = None
    content_hash: str = ""

    @property
    def protected(self) -> bool:
        return self.manual or self.status in PROTECTED_STATUSES


def new_id(existing: set[str]) -> str:
    for _ in range(8):
        identity = "task-" + uuid.uuid4().hex[:12]
        if identity not in existing:
            return identity
    raise StoreError("could not allocate a task id")


def valid_id(value: str) -> bool:
    return bool(_ID.fullmatch(value or ""))


def _parse_evidence(lines: list[str]) -> list[Evidence]:
    quotes: list[Evidence] = []
    current: list[str] = []
    locator = ""

    def flush() -> None:
        nonlocal locator
        if current:
            quotes.append(Evidence("\n".join(current).strip(), locator))
        current.clear()
        locator = ""

    for line in lines:
        if line.startswith("> locator:"):
            locator = line.split(":", 1)[1].strip()
        elif line.startswith(">"):
            current.append(line[1:].lstrip())
        elif line.strip() == "":
            flush()
    flush()
    return [item for item in quotes if item.quote]


def _section_map(lines: list[str]) -> tuple[dict[str, list[str]], dict[str, str]]:
    sections: dict[str, list[str]] = {}
    order: list[str] = []
    name: str | None = None
    for line in lines:
        if line.startswith("## "):
            name = line[3:].strip()
            order.append(name)
            sections[name] = []
            continue
        if name is not None:
            sections[name].append(line)
    extras: dict[str, str] = {}
    for section_name in order:
        if section_name in STANDARD_SECTIONS:
            continue
        extras[section_name] = "\n".join(sections[section_name]).strip("\n")
    return sections, extras


def parse_card(text: str, path: Path | None = None) -> Card:
    lines = text.splitlines()
    fields: dict[str, str] = {}
    title = ""
    body: list[str] = []
    seen_section = False
    for line in lines:
        if not seen_section and line.startswith("## "):
            seen_section = True
        if not seen_section:
            field_match = _FIELD.match(line.strip())
            if field_match:
                fields[field_match.group(1).lower()] = field_match.group(2).strip()
                continue
            title_match = _TITLE.match(line)
            if title_match and not title:
                title = title_match.group(1).strip()
                continue
            if line.strip() == "":
                continue
            seen_section = True
        body.append(line)

    identity = fields.get("id", "")
    status = fields.get("status", "")
    if not valid_id(identity):
        raise ValidationError(f"card is missing a valid id: {(path.name if path else identity)}")
    if status not in STATUSES:
        raise ValidationError(f"unknown status on {identity}: {status or '(empty)'}")
    sections, extras = _section_map(body)
    why = "\n".join(sections.get("Why this was kept", [])).strip()
    where = "\n".join(sections.get("Where it stopped", [])).strip()
    history = [
        item[2:].strip()
        for item in sections.get("History", [])
        if item.startswith("- ")
    ]
    origin = [
        item[2:].strip()
        for item in sections.get("Origin", [])
        if item.startswith("- ")
    ]
    manual = fields.get("manual", "false").casefold() == "true"
    card = Card(
        status=status,
        id=identity,
        manual=manual,
        authorization=fields.get("authorization") or "record_only",
        owner=fields.get("owner") or "unspecified",
        actor=fields.get("actor") or "unspecified",
        updated=fields.get("updated", ""),
        stop=fields.get("stop", ""),
        resume_when=fields.get("resume_when", ""),
        source=fields.get("source", ""),
        suggestion_origin=fields.get("suggestion_origin", ""),
        title=title or identity,
        why=why,
        where_stopped=where,
        evidence=_parse_evidence(sections.get("Evidence", [])),
        origin_lines=origin,
        history=history,
        extra_sections=extras,
        path=path,
        content_hash=sha256_text(text),
    )
    return card


def render_card(card: Card) -> str:
    lines = [
        f"**status:** {card.status}",
        f"**id:** {card.id}",
        f"**manual:** {'true' if card.manual else 'false'}",
        f"**authorization:** {card.authorization}",
        f"**owner:** {card.owner}",
        f"**actor:** {card.actor}",
        f"**updated:** {card.updated}",
        f"**stop:** {one_line(card.stop)}",
        f"**resume_when:** {one_line(card.resume_when)}",
        f"**source:** {one_line(card.source)}",
        f"**suggestion_origin:** {card.suggestion_origin}",
        "",
        f"# {card.title}",
        "",
        "## Why this was kept",
        "",
        card.why.strip() or "No reason was recorded.",
        "",
        "## Where it stopped",
        "",
        card.where_stopped.strip() or one_line(card.stop) or "No stop point was recorded.",
        "",
        "## Resume condition",
        "",
        card.resume_when.strip() or "No resume condition was recorded.",
        "",
        "## Evidence",
        "",
    ]
    if not card.evidence:
        lines.append("No quote was recorded.")
        lines.append("")
    for item in card.evidence:
        for quote_line in item.quote.splitlines() or [""]:
            lines.append(f"> {quote_line}")
        if item.locator:
            lines.append(f"> locator: {item.locator}")
        lines.append("")
    lines.extend(["## Origin", ""])
    if card.origin_lines:
        for item in card.origin_lines:
            lines.append(f"- {item}")
    else:
        lines.append("- No origin was recorded.")
    lines.extend(["", "## History", ""])
    if card.history:
        for item in card.history:
            lines.append(f"- {item}")
    else:
        lines.append("- No history was recorded.")
    lines.append("")
    for name, content in card.extra_sections.items():
        lines.extend([f"## {name}", "", content.strip(), ""])
    text = "\n".join(lines).rstrip() + "\n"
    return text


def one_line(value: str) -> str:
    return " ".join(value.split())


def slugify(title: str) -> str:
    ascii_title = title.encode("ascii", "ignore").decode().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_title).strip("-")
    return (slug or "task")[:40].strip("-") or "task"


def card_path(root: Path, card: Card) -> Path:
    return root / f"{slugify(card.title)}--{card.id}.md"


def load_cards(root: Path) -> list[Card]:
    if not root.exists():
        return []
    if not root.is_dir():
        raise StoreError("tasks directory is not a directory")
    cards: list[Card] = []
    seen: set[str] = set()
    root_resolved = root.resolve()
    for path in sorted(root.rglob("*.md")):
        if ".tasks-recapture" in path.parts:
            continue
        if path.is_symlink():
            raise StoreError(f"refusing to read a symlinked card: {path.name}")
        resolved = path.resolve()
        if root_resolved not in resolved.parents and resolved != root_resolved:
            raise StoreError("card path escapes the task directory")
        text = path.read_text(encoding="utf-8")
        if "**id:**" not in text.lower() and "**id：**" not in text:
            continue
        card = parse_card(text, path)
        if card.id in seen:
            raise StoreError(f"duplicate task id: {card.id}")
        seen.add(card.id)
        cards.append(card)
    return cards


def write_card(root: Path, card: Card, expected_sha256: str | None) -> Card:
    path = card.path or card_path(root, card)
    resolve_inside(root, path)
    text = render_card(card)
    digest = atomic_write(path, text, expected_sha256)
    card.path = path
    card.content_hash = digest
    return card
