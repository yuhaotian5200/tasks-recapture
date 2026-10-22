# Security

`tasks-recapture` reads a file you name, optionally sends that file to an API you name, and writes Markdown under a directory you name. It does not execute task text.

## Report a problem

Open a private security advisory on this repository if the report describes a way to write outside the task directory, leak `TASKS_RECAPTURE_API_KEY`, run a command from a transcript or model response, or bypass status protection. A public issue is enough for a behavior bug that does not expose a key or a file.

Please include the version, the command line with the key removed, and a synthetic transcript. Do not send real chats, account data, or live API keys.

## What the program trusts

| Input | How it is treated |
| --- | --- |
| Transcript text | Untrusted data. Markers record a role. A role of `system` has no special power. |
| Model JSON | Untrusted until the schema check and the exact-quote check pass. |
| Decisions file and `mark` | A person choosing what to record. Still not permission to execute the task. |
| Config file | Task directory, timezone, model name, API base, timeout, provider. Secret fields are refused. |
| `TASKS_RECAPTURE_API_KEY` | Used only as the bearer token of a live request after `--send`. It is not written to cards, the ledger, or the log line this program prints. |
| Task directory | The only place cards and resume state are written. |

## Controls that exist

- Writable suggestions must use `add`, `update`, or `ignore`, and every quote must be an exact substring of at least 8 characters.
- `command`, `shell`, `tool`, `authorization`, and similar fields reject the whole suggestion. A top-level field with those names is ignored.
- Import cannot set `in_progress` or `done`. `paused` and `done` cards, and cards with `manual: true`, keep their status, stop point, and resume condition.
- Uncertain title matches, including a model id that the titles do not support, are not applied by `--yes`.
- The live client returns before `urlopen` unless `--send` is set and the key is present.
- Card writes are temp-file plus rename, then a read-back compare. A hash mismatch keeps the newer file.
- Symlinks and paths that resolve outside the task directory are refused.
- Labels stored on cards use a relative path or a bare file name, plus a SHA-256 of the normalized text.

## Limits

- `--yes` will record an unambiguous but wrong suggestion from a hostile or confused model, including an ignore. Review the preview when the model is not trusted.
- A certain fuzzy match can attach a follow-up to the wrong card under `--yes`. The interactive prompt can choose a new card instead. The matcher is token overlap with a small synonym list, not a semantic model.
- Exact quotes mean a live model that paraphrases evidence will have those suggestions rejected. That behavior has not been measured on a live API.
- The API base URL is whatever you configure. `--send` delivers the transcript to that host.
- File locking uses POSIX `fcntl`. Other platforms are not implemented.
- This file is a description of the current command-line tool. It is not a claim that a past private desktop app was audited.
