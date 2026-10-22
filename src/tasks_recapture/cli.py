"""Command line. Interactive confirm is the default when stdin is a terminal."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from tasks_recapture import __version__
from tasks_recapture.cards import load_cards
from tasks_recapture.config import build_settings
from tasks_recapture.errors import RecaptureError
from tasks_recapture.flow import (
    import_transcript,
    mark_status,
    render_list,
    render_review,
    resume_run,
    review_cards,
)
from tasks_recapture.model import (
    FileMockProvider,
    HeuristicMockProvider,
    OpenAICompatibleProvider,
)


def _provider(settings, send: bool):
    if settings.provider == "mock":
        if settings.mock_script:
            return FileMockProvider(settings.mock_script)
        return HeuristicMockProvider()
    if settings.provider == "openai-compatible":
        return OpenAICompatibleProvider(
            model=settings.model,
            api_base=settings.api_base,
            timeout=settings.timeout,
            allow_send=send,
        )
    raise RecaptureError(
        "Set --provider mock, or --provider openai-compatible with "
        "TASKS_RECAPTURE_API_KEY and --send. No provider was called."
    )


def _decisions(path: str | None) -> dict | None:
    if not path:
        return None
    file_path = Path(path)
    try:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RecaptureError("decisions file must be a JSON object") from exc
    if not isinstance(payload, dict):
        raise RecaptureError("decisions file must be a JSON object")
    return payload


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--tasks-dir", help="directory of Markdown task cards")
    parser.add_argument("--timezone", help="IANA timezone used for timestamps")
    parser.add_argument("--config", help="JSON config file")
    parser.add_argument("--now", help="ISO timestamp override, used for tests and examples")


def _settings_from(args, send: bool = False):
    return build_settings(
        config_path=Path(args.config) if getattr(args, "config", None) else None,
        tasks_dir=args.tasks_dir,
        timezone=args.timezone,
        model=getattr(args, "model", None),
        api_base=getattr(args, "api_base", None),
        timeout=getattr(args, "timeout", None),
        provider=getattr(args, "provider", None),
        mock_script=getattr(args, "mock_script", None),
        send=send,
    )


def _input_fn(yes: bool, decisions: dict | None):
    if yes or decisions is not None or not sys.stdin.isatty():
        return None
    return input


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tasks-recapture",
        description=(
            "Recover unfinished tasks from a UTF-8 transcript into local Markdown "
            "cards. Saving a card does not authorize anyone to execute it."
        ),
    )
    parser.add_argument("--version", action="version", version=f"tasks-recapture {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    import_parser = sub.add_parser("import", help="propose cards from a transcript and confirm")
    import_parser.add_argument("transcript", help="UTF-8 .txt or .md transcript")
    _common(import_parser)
    import_parser.add_argument("--model", help="model name for a live provider")
    import_parser.add_argument("--api-base", help="OpenAI-compatible API base URL")
    import_parser.add_argument("--timeout", type=float, help="live request timeout in seconds")
    import_parser.add_argument("--provider", choices=("mock", "openai-compatible"))
    import_parser.add_argument("--mock-script", help="JSON file of mock suggestions")
    import_parser.add_argument(
        "--yes",
        action="store_true",
        help="accept unambiguous suggestions; uncertain matches stay pending",
    )
    import_parser.add_argument("--decisions", help="JSON map of suggestion id to a decision")
    import_parser.add_argument(
        "--send",
        action="store_true",
        help="allow sending the transcript to the configured live API",
    )
    import_parser.add_argument(
        "--stop-after",
        choices=("propose", "before-write"),
        help="save a resumable checkpoint and exit before that step",
    )
    import_parser.add_argument(
        "--reanalyze",
        action="store_true",
        help="call the provider again even if this transcript was already processed",
    )

    resume_parser = sub.add_parser("resume", help="continue a saved run")
    _common(resume_parser)
    resume_parser.add_argument("--run-id")
    resume_parser.add_argument("--yes", action="store_true")
    resume_parser.add_argument("--decisions")

    list_parser = sub.add_parser("list", help="list task cards")
    _common(list_parser)

    show_parser = sub.add_parser("show", help="print one task card")
    show_parser.add_argument("card_id")
    _common(show_parser)

    mark_parser = sub.add_parser(
        "mark",
        help="set a status by hand; this does not execute the task",
    )
    mark_parser.add_argument("card_id")
    mark_parser.add_argument(
        "--status",
        required=True,
        choices=("not_started", "in_progress", "paused", "done"),
    )
    _common(mark_parser)

    review_parser = sub.add_parser(
        "review",
        help="report resume conditions without changing any card",
    )
    review_parser.add_argument("--transcript", help="optional new UTF-8 transcript")
    _common(review_parser)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "import":
            settings = _settings_from(args, send=args.send)
            decisions = _decisions(args.decisions)
            result = import_transcript(
                Path(args.transcript),
                tasks_dir=settings.tasks_dir,
                timezone_name=settings.timezone,
                provider=_provider(settings, args.send),
                now=args.now,
                yes=args.yes,
                decisions=decisions,
                stop_after=args.stop_after,
                reanalyze=args.reanalyze,
                input_fn=_input_fn(args.yes, decisions),
                output_fn=print,
            )
            sys.stdout.write(result.render())
            return result.exit_code
        if args.command == "resume":
            settings = _settings_from(args)
            decisions = _decisions(args.decisions)
            result = resume_run(
                settings.tasks_dir,
                run_id=args.run_id,
                timezone_name=settings.timezone,
                now=args.now,
                yes=args.yes,
                decisions=decisions,
                input_fn=_input_fn(args.yes, decisions),
                output_fn=print,
            )
            sys.stdout.write(result.render())
            return result.exit_code
        if args.command == "list":
            settings = _settings_from(args)
            sys.stdout.write(render_list(load_cards(settings.tasks_dir)))
            return 0
        if args.command == "show":
            settings = _settings_from(args)
            cards = load_cards(settings.tasks_dir)
            card = next((item for item in cards if item.id == args.card_id), None)
            if card is None or card.path is None:
                raise RecaptureError(f"{args.card_id} was not found")
            sys.stdout.write(card.path.read_text(encoding="utf-8"))
            if not card.path.read_text(encoding="utf-8").endswith("\n"):
                sys.stdout.write("\n")
            return 0
        if args.command == "mark":
            settings = _settings_from(args)
            result = mark_status(
                settings.tasks_dir,
                args.card_id,
                args.status,
                timezone_name=settings.timezone,
                now=args.now,
            )
            sys.stdout.write(result.render())
            return result.exit_code
        if args.command == "review":
            settings = _settings_from(args)
            hints = review_cards(
                settings.tasks_dir,
                Path(args.transcript) if args.transcript else None,
            )
            sys.stdout.write(render_review(hints))
            return 0
    except RecaptureError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
