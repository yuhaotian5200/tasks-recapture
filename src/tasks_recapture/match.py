"""Title matching with synonym normalization.

Certain matches may be proposed as updates. Uncertain matches are returned to
the human. This module never writes cards and never merges them.
"""

from __future__ import annotations

import re

# Multi-word and CJK phrases, longest first. Replacements are canonical tokens.
_PHRASES: tuple[tuple[str, str], ...] = (
    ("set aside", " hold "),
    ("put aside", " hold "),
    ("on hold", " hold "),
    ("pick up", " resume "),
    ("起草", "写作"),
    ("撰写", "写作"),
)

_WORD_SYNONYMS = {
    "draft": "write",
    "author": "write",
    "compose": "write",
    "memo": "note",
    "notes": "note",
    "finish": "complete",
    "finished": "complete",
    "done": "complete",
    "fix": "repair",
    "bug": "defect",
    "ship": "release",
    "publish": "release",
    "pause": "hold",
    "paused": "hold",
    "shelve": "hold",
    "shelved": "hold",
    "arrive": "arrive",
    "arrives": "arrive",
    "arrived": "arrive",
    "arrival": "arrive",
    "start": "begin",
    "starts": "begin",
    "begin": "begin",
    "begins": "begin",
}

_STOP = {
    "a",
    "an",
    "the",
    "to",
    "for",
    "of",
    "and",
    "or",
    "in",
    "on",
    "with",
    "this",
    "that",
    "it",
    "is",
    "be",
    "we",
    "you",
    "i",
    "let",
    "lets",
    "please",
    "once",
    "when",
    "until",
    "before",
    "after",
    "from",
    "into",
    "about",
    "just",
    "our",
    "your",
    "they",
    "them",
    "then",
    "than",
    "still",
    "only",
    "dont",
    "do",
    "not",
    "no",
    "so",
    "if",
    "at",
    "by",
    "as",
    "was",
    "were",
    "are",
    "will",
    "would",
    "should",
    "could",
    "have",
    "has",
    "had",
    "can",
    "need",
    "want",
    "make",
    "task",
    "item",
    "while",
    "also",
    "that",
}


def tokenize(text: str) -> set[str]:
    """Normalize synonyms, then return content tokens and CJK bigrams."""
    folded = text.casefold()
    for source, target in _PHRASES:
        folded = folded.replace(source.casefold(), target)
    tokens: set[str] = set()
    for word in re.findall(r"[a-z0-9]+", folded):
        word = _WORD_SYNONYMS.get(word, word)
        if word in _STOP or len(word) < 2:
            continue
        tokens.add(word)
    for run in re.findall(r"[\u4e00-\u9fff]+", folded):
        if len(run) == 1:
            tokens.add(run)
            continue
        tokens.add(run)
        for index in range(len(run) - 1):
            tokens.add(run[index : index + 2])
    return tokens


def score_pair(left: str, right: str) -> tuple[float, int]:
    left_tokens = tokenize(left)
    right_tokens = tokenize(right)
    if not left_tokens or not right_tokens:
        return 0.0, 0
    overlap = left_tokens & right_tokens
    union = left_tokens | right_tokens
    return len(overlap) / len(union), len(overlap)


def kind_for(score: float, overlap: int) -> str:
    """Return certain, uncertain, or none. Certain requires strong overlap."""
    if score >= 0.999 and overlap >= 1:
        return "certain"
    if score >= 0.75 and overlap >= 2:
        return "certain"
    if score >= 0.30 and overlap >= 2:
        return "uncertain"
    return "none"


def match_titles(title: str, cards: list, hinted_id: str | None = None) -> dict:
    """Compare `title` with existing cards.

    A model-supplied id is only a hint. If the titles do not clearly match,
    the hint becomes an uncertain candidate instead of a merge.
    """
    scored: list[dict] = []
    seen: set[str] = set()
    for card in cards:
        score, overlap = score_pair(title, card.title)
        kind = kind_for(score, overlap)
        hinted = bool(hinted_id and card.id == hinted_id)
        if kind == "none" and hinted:
            kind = "uncertain"
        if kind == "none":
            continue
        seen.add(card.id)
        scored.append(
            {
                "id": card.id,
                "title": card.title,
                "status": card.status,
                "score": round(score, 4),
                "kind": kind,
                "hinted": hinted,
            }
        )
    if hinted_id and hinted_id not in seen:
        hinted_card = next((card for card in cards if card.id == hinted_id), None)
        if hinted_card is not None:
            score, _overlap = score_pair(title, hinted_card.title)
            scored.append(
                {
                    "id": hinted_card.id,
                    "title": hinted_card.title,
                    "status": hinted_card.status,
                    "score": round(score, 4),
                    "kind": "uncertain",
                    "hinted": True,
                }
            )

    certain = [item for item in scored if item["kind"] == "certain"]
    if len(certain) == 1 and len(scored) == 1:
        return {"kind": "certain", "candidates": certain}
    if scored:
        for item in scored:
            item["kind"] = "uncertain"
        scored.sort(key=lambda item: (-item["score"], item["id"]))
        return {"kind": "uncertain", "candidates": scored}
    return {"kind": "none", "candidates": []}
