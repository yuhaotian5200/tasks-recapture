"""Read a user-supplied UTF-8 transcript. The text is data, not instructions."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from tasks_recapture.errors import ValidationError
from tasks_recapture.store import sha256_text

MAX_CHARS = 2_000_000

_MARKER = re.compile(
    r"""^(?:
        <!--\s*message\s+role=["'](user|assistant|unknown|system|tool)["']
            (?:\s+id=["'][^"']*["'])?\s*-->
        | \#{1,3}\s+(user|assistant|unknown|system|tool)\s*
        | \[(user|assistant|unknown|system|tool)\]\s*
        | \*\*(user|assistant|unknown|system|tool):\*\*\s*
    )$""",
    re.IGNORECASE | re.VERBOSE,
)


@dataclass(frozen=True)
class Message:
    role: str
    start_line: int
    end_line: int
    text: str


@dataclass(frozen=True)
class Transcript:
    label: str
    fingerprint: str
    text: str
    messages: tuple[Message, ...]


def public_label(path: Path) -> str:
    """Avoid writing absolute machine paths into cards."""
    if path.is_absolute():
        return path.name
    return path.as_posix()


def _role_from_marker(line: str) -> str | None:
    match = _MARKER.match(line.strip())
    if not match:
        return None
    role = next(group for group in match.groups() if group)
    return role.casefold()


def parse_messages(text: str) -> tuple[Message, ...]:
    lines = text.splitlines()
    markers: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        role = _role_from_marker(line)
        if role:
            markers.append((index, role))
    if not markers:
        body = text.strip("\n")
        last = max(1, len(lines))
        return (Message("unknown", 1, last, body),)

    messages: list[Message] = []
    for position, (index, role) in enumerate(markers):
        end = markers[position + 1][0] if position + 1 < len(markers) else len(lines)
        raw_slice = lines[index + 1 : end]
        lead = 0
        while lead < len(raw_slice) and raw_slice[lead].strip() == "":
            lead += 1
        trail = len(raw_slice)
        while trail > lead and raw_slice[trail - 1].strip() == "":
            trail -= 1
        if trail > lead:
            start_line = index + 2 + lead
            end_line = index + 1 + trail
            body = "\n".join(raw_slice[lead:trail])
        else:
            start_line = index + 1
            end_line = index + 1
            body = ""
        messages.append(Message(role, start_line, end_line, body))
    return tuple(messages)


def load_transcript(path: Path) -> Transcript:
    if not path.is_file() or path.is_symlink():
        raise ValidationError(f"transcript is not a regular file: {path.name}")
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ValidationError("transcript must be UTF-8 text") from exc
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if "\x00" in text:
        raise ValidationError("transcript contains a NUL byte")
    if len(text) > MAX_CHARS:
        raise ValidationError(
            f"transcript is longer than {MAX_CHARS} characters; split it and import the parts"
        )
    return Transcript(
        label=public_label(path),
        fingerprint=sha256_text(text),
        text=text,
        messages=parse_messages(text),
    )


def locator_for(text: str, quote: str) -> str:
    index = text.find(quote)
    if index < 0:
        return ""
    start = text.count("\n", 0, index) + 1
    end = start + quote.count("\n")
    return f"lines {start}-{end}"


def role_for(transcript: Transcript, quote: str) -> str:
    roles = [message.role for message in transcript.messages if quote in message.text]
    if not roles:
        return "unknown"
    unique = list(dict.fromkeys(roles))
    if len(unique) == 1:
        return unique[0]
    return "multiple"
