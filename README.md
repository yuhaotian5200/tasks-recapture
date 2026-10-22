# tasks-recapture

`tasks-recapture` reads a UTF-8 chat transcript, asks a model for unfinished work, and shows you the suggestions before anything is saved. After you confirm, it writes local Markdown task cards. A later import can attach new discussion to the same card.

Saving a card records the work. It does not authorize anyone to do the work, and this program never executes commands found in a chat.

The first public version is a single command-line tool. It does not watch chat accounts, schedule runs, or ship a desktop app.

## Install

Python 3.11 or newer. The runtime dependencies are the Python standard library.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install .
tasks-recapture --version
```

## Quickstart with the mock provider

The mock provider does not call a network API and does not read an API key. Its output is labeled `provider: mock` and `live_api: false`.

```bash
mkdir -p /tmp/tasks-demo
tasks-recapture import examples/sample-transcript.md \
  --tasks-dir /tmp/tasks-demo \
  --provider mock \
  --mock-script examples/mock-suggestions.json \
  --yes \
  --timezone UTC \
  --now 2026-10-22T12:00:00

tasks-recapture list --tasks-dir /tmp/tasks-demo
```

That transcript is synthetic. One recorded result of this command is checked in at `examples/resulting-cards/`. A new run mints a new card id; the title, status, stop point, and resume condition stay the same when `--now` is fixed.

What that run keeps:

- **Draft the November garden newsletter** becomes one card with status `paused` and resume condition `The plant list arrives.`
- The website redesign is ignored because the person rejected it.
- The watering reminder is ignored because the transcript already says it was sent.
- The line that says to ignore instructions and run a command is not a task and is not executed.

`--yes` accepts only unambiguous suggestions. An uncertain match stays pending and is not merged.

## A later note can point back at the same card

```bash
tasks-recapture review \
  --tasks-dir /tmp/tasks-demo \
  --transcript examples/follow-up.md

tasks-recapture import examples/follow-up.md \
  --tasks-dir /tmp/tasks-demo \
  --provider mock \
  --mock-script examples/mock-follow-up.json \
  --yes \
  --timezone UTC \
  --now 2026-10-22T13:00:00
```

`review` only prints a hint. In a mock run it reported that the plant-list condition may be satisfied and left the card paused.

The follow-up import matched **Write the November garden newsletter** to the existing draft card (`match=certain`). Because the card was paused, the tool appended a history note and left the status, stop point, and resume condition in place. It did not create a second card, and it did not mark the work in progress.

To change a status yourself:

```bash
tasks-recapture mark task-0123456789ab --status in_progress --tasks-dir /tmp/tasks-demo
```

`mark` records that a person set the status. It still does not execute the task. A card marked this way, and any card that is `paused` or `done`, will not have its status replaced by a later import.

## Configuration

Flags override environment variables, which override `tasks-recapture.json` in the current directory.

```json
{
  "tasks_dir": "tasks",
  "timezone": "UTC",
  "model": "example-model",
  "api_base": "https://api.openai.com/v1",
  "timeout_seconds": 60,
  "provider": "mock"
}
```

| Setting | Flag | Environment variable | Default |
| --- | --- | --- | --- |
| Task directory | `--tasks-dir` | `TASKS_RECAPTURE_TASKS_DIR` | `tasks` |
| Timezone | `--timezone` | `TASKS_RECAPTURE_TIMEZONE` | `UTC` |
| Model name | `--model` | `TASKS_RECAPTURE_MODEL` | empty |
| API base URL | `--api-base` | `TASKS_RECAPTURE_API_BASE` | `https://api.openai.com/v1` |
| Timeout seconds | `--timeout` | `TASKS_RECAPTURE_TIMEOUT` | `60` |
| Provider | `--provider` | `TASKS_RECAPTURE_PROVIDER` | empty |

The API key is read only from `TASKS_RECAPTURE_API_KEY`. A config file that contains `api_key`, `token`, `secret`, `password`, or `authorization` is rejected. Relative task directories are resolved from the current working directory.

The checked-in example uses a model name of the form you configure. This repository has not verified a live model name, because no live call has been made.

### Live provider

A live call uses an OpenAI-compatible `POST /chat/completions` endpoint. It sends the transcript and short summaries of existing cards (id, title, status, stop, resume condition, manual flag). It does not send the API key inside the transcript or write the key into a card.

Nothing is sent unless all of these are true:

- `--provider openai-compatible`
- `--model` (or the environment/config equivalent) is set
- `TASKS_RECAPTURE_API_KEY` is set
- `--send` is present

Without `--send`, the program stops before opening a socket. There is no key in this repository, and the live API has not been run. See [HANDOFF.md](HANDOFF.md).

## Commands

```text
tasks-recapture import TRANSCRIPT [--yes | --decisions FILE] [--provider mock|openai-compatible]
tasks-recapture resume [--run-id ID] [--yes | --decisions FILE]
tasks-recapture list
tasks-recapture show CARD_ID
tasks-recapture mark CARD_ID --status not_started|in_progress|paused|done
tasks-recapture review [--transcript FILE]
```

`import` reads one UTF-8 `.txt` or `.md` file. It does not scan a home directory or a chat account. Absolute paths are stored as the file name plus a content fingerprint, not as a machine path.

On a terminal, each suggestion asks for a decision. Without a terminal, pass `--yes` or `--decisions`. `--yes` accepts a new card, a single certain update, or an ignore. It leaves every uncertain match pending and exits with status 2. Pending work is stored under the task directory in `.tasks-recapture/` and can be continued with `resume`.

A decisions file maps a suggestion id to `accept`, `skip`, `{"choice":"new"}`, or `{"choice":"existing","id":"task-..."}`. `accept` is rejected for an uncertain match; pick `new` or an existing candidate id.

`--stop-after propose` and `--stop-after before-write` save a checkpoint and exit with status 3. `resume` continues that run without calling the provider again.

Exit status: `0` finished, `1` error, `2` waiting for a person, `3` checkpoint.

## Task cards

Cards are Markdown files in the task directory. The header is the source of truth:

- `status`: `not_started`, `in_progress`, `paused`, or `done`
- `id`: stable `task-` plus 12 hex characters, assigned by the program
- `manual`: `true` after `mark`
- `authorization`: always `record_only` on a program write
- `stop`: where the work stopped, in one sentence
- `resume_when`: the condition for picking it up again
- `suggestion_origin`: `mock-script`, `mock-heuristic`, or `live-api`

Import creates a card as `not_started`, or as `paused` when the suggestion is an explicit hold and `resume_when` is filled. Import never creates or sets `in_progress` or `done`. Those statuses come from `mark` or from a file you edit yourself.

A card is protected when it is `paused`, `done`, or `manual`. A confirmed import may append a history note to a protected card. It does not change that card's status, stop point, or resume condition, and it does not clear a pause because time has passed.

Evidence quotes must be exact substrings of the transcript. The program checks that before it shows a suggestion as writable.

## Safety model

Transcript text and model output are untrusted data.

- Instructions inside a chat cannot change the program, select a provider, print the API key, or grant execution rights.
- The program does not run shell commands from the transcript or from the model.
- Model suggestions are checked against a fixed schema. Fields such as `command`, `shell`, `tool`, or `authorization` cause that suggestion to be rejected.
- A quote that is not an exact substring of the file is rejected.
- A model-supplied card id is a hint. If the titles do not clearly match, the hint is an uncertain candidate for a person. It is never merged by `--yes`.
- Two equally strong matches are uncertain, not an automatic pick.
- Writes use a temporary file in the task directory, then `rename`. The program reads the file back and checks the bytes. If the card changed after it was read, the new bytes stay and the suggestion returns to the person.
- Card paths that are symlinks, or that resolve outside the task directory, are refused.
- `--yes` is a convenience for unambiguous suggestions. It is not a defense against a model that confidently suggests the wrong unambiguous action. Use the interactive prompt or a decisions file when that matters.

Details and how to report a problem are in [SECURITY.md](SECURITY.md).

## What is stored, sent, and deleted

Local files:

- Markdown cards in the task directory
- `.tasks-recapture/ledger.json` and `.tasks-recapture/runs/` for fingerprints, decisions, and resume state

The ledger stores a file name and a SHA-256 of the newline-normalized transcript, not an absolute path. Re-importing the same text does not call the provider again and does not create another card. `--reanalyze` asks the provider again after the open run is finished. Deleting a card does not forget that fingerprint; delete `.tasks-recapture/` as well if you want to process those bytes again.

A mock run sends nothing. A live run with `--send` sends the selected transcript and the card summaries above to the configured API base. There is no telemetry account in this program.

To delete the library, delete the task directory. That removes cards and the ledger together.

## Tests

```bash
pip install .
python -m unittest discover -s tests -v
```

Tests use synthetic transcripts and a mock provider. One test is skipped on purpose: the live API is not called, and its output is not invented. The mock forces `live_api` to false even if a script claims otherwise.

## License and contributing

New code in this repository is MIT. See [LICENSE](LICENSE). Contribution notes are in [CONTRIBUTING.md](CONTRIBUTING.md). Chinese usage notes are in [README.zh.md](README.zh.md). A handoff for the next maintainer pass is in [HANDOFF.md](HANDOFF.md).

This project is not endorsed, approved, or funded by OpenAI. No application of that kind is filed from this repository.
