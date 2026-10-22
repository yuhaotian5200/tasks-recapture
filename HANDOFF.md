# HANDOFF

Ready for Codex to pick up. This file is the public state of `tasks-recapture` 0.1.0. It does not contain private paths, private chats, or an API key.

No OpenAI Codex for Open Source application was submitted from this work. This repository does not claim that OpenAI endorsed, approved, or funded the project.

## What exists

A standalone Python command-line tool in `src/tasks_recapture/`. It:

1. Reads one UTF-8 `.txt` or `.md` transcript and records role, line locator, and a SHA-256 of the newline-normalized text.
2. Asks a provider for `add`, `update`, and `ignore` suggestions with exact evidence quotes.
3. Shows a preview and waits for a person, or accepts unambiguous items with `--yes` / `--decisions`.
4. Writes Markdown cards by temp file and rename, then reads them back.
5. Matches titles with a small synonym list. Uncertain matches stay with the person.
6. Refuses to replace the status of a `paused`, `done`, or manually marked card.
7. Stores resume state so an interrupted run can continue, and skips a transcript whose fingerprint is already complete.
8. Can print resume-condition hints with `review` without editing cards.

The public example is `examples/sample-transcript.md` plus `examples/mock-suggestions.json`. One resulting card is in `examples/resulting-cards/`. Its `suggestion_origin` is `mock-script`.

Out of this version, on purpose: account monitoring, scheduling, executing tasks, and a desktop app.

## Install and run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install .
tasks-recapture import examples/sample-transcript.md \
  --tasks-dir /tmp/tasks-demo \
  --provider mock \
  --mock-script examples/mock-suggestions.json \
  --yes \
  --timezone UTC \
  --now 2026-10-22T12:00:00
tasks-recapture list --tasks-dir /tmp/tasks-demo
tasks-recapture review --tasks-dir /tmp/tasks-demo --transcript examples/follow-up.md
```

Python 3.11+ is required. Install and runtime dependencies are the standard library plus `setuptools` to build the package. The API key, when a later live run needs one, is only `TASKS_RECAPTURE_API_KEY`. A live call also needs `--provider openai-compatible`, a model name, and `--send`.

## Tests

```bash
python -m unittest discover -s tests -v
```

The suite is synthetic. It covers a duplicate import, an interrupted run resumed without a second provider call, hostile text in the transcript and in a mock model payload, protection of done / paused / manual status, and uncertain-match escalation. Mock results are forced to `provider: mock` and `live_api: false`.

`test_live_api_roundtrip` is skipped. The skip message is the status of the live API: **NOT TESTED**. No live response is checked in.

Continuous integration is `.github/workflows/ci.yml`. It runs the unit tests on Python 3.11 and 3.12 for pushes to `main` and for pull requests. It requests only `contents: read` and does not use repository secrets.

## Real gaps and blockers

- **Live API: NOT TESTED.** No API key was available. Do not treat the mock cards as model-quality evidence. The default API base is `https://api.openai.com/v1`, and any model name is whatever the operator sets. Neither the base URL nor a model name has been verified with a successful call.
- Exact-quote checking will reject a live model that paraphrases evidence. How often that happens is unknown.
- `--yes` applies unambiguous suggestions, including ignores. A wrong but schema-valid model can drop or create a card if the operator passes `--yes`. It will not auto-merge an uncertain match.
- A single certain fuzzy match is applied by `--yes`. The threshold can attach the wrong follow-up. Interactive mode can force a new card. The matcher is not an embedding model. Very different wording for the same task can also miss and create a second card.
- Import never sets `in_progress` or `done`. Protected cards (`paused`, `done`, `manual: true`) also keep their stop point and resume condition; only a history note is appended. `review` does not reopen them. A person uses `mark`.
- There is no rename command and no command that merges two existing cards except by confirming an uncertain or certain link during import.
- Deleting a card file does not clear the ledger. The same bytes stay "already processed" until `.tasks-recapture/` is removed or the open run is finished and `--reanalyze` is used. `--reanalyze` is refused while a run is still open.
- Transcripts longer than 2,000,000 characters are rejected instead of truncated. The operator has to split them.
- Locking uses POSIX `fcntl`. Windows is not implemented.
- The live client speaks chat completions with `response_format: json_object`. Other vendor payloads are not implemented.
- Card Markdown is the header and section layout this program writes. Arbitrary Markdown is not a supported card format.
- Task ids are random. The file in `examples/resulting-cards/` will not match the id from a fresh run.

## What was not copied into this repository

An internal reference bundle was checked against its manifest before this version was written: 12 files, every SHA-256 matched, nothing missing and nothing extra. That bundle was not committed. Private paths, private task text, and private scripts were not copied.

A private desktop client existed in that reference and was out of scope here, so it is not in this tree. That client incorporated third-party window code from [Tendedero](https://github.com/alejandrobujan/tendedero) (upstream commit `ed0618a67cc59e0a8621b97bb5e32ab9af3b0b69` in the reference notes). This repository does not vendor that code, so it does not carry the Tendedero license file. Anyone who later vendors it must keep Alejandro Buján's MIT copyright notice and must not reuse the Tendedero name or icon.

## License

New code is MIT, copyright 2026 yuhaotian5200. See `LICENSE`.
