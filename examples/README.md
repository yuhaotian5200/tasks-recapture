# Synthetic example

These files are invented. They are not a chat export.

| File | Role |
| --- | --- |
| `sample-transcript.md` | First transcript, including an unadopted idea, a finished reminder, and a line that tries to override the program |
| `mock-suggestions.json` | Mock provider script for that transcript. It is not a live API response |
| `follow-up.md` | Later note that the plant list arrived |
| `mock-follow-up.json` | Mock script for the follow-up |
| `resulting-cards/` | One card produced by the mock importer with `--now 2026-10-22T12:00:00` and `--timezone UTC` |

The card id in `resulting-cards/` belongs to that recorded run. Running the command again creates a different id.

The sample's override line is data. The tests, not this mock script, are what reject a model response that asks the program to execute a command.
