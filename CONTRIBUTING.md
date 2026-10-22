# Contributing

Issues and patches are welcome. Keep them on this tool: importing a transcript, confirming suggestions, and writing local task cards.

- Use synthetic transcripts. Do not commit real chats, personal task libraries, account data, or API keys.
- New program code in this repository stays under the MIT license in [LICENSE](LICENSE).
- Run `python -m unittest discover -s tests -v` before sending a change. The skipped live-API test must stay skipped unless a maintainer runs it on purpose and labels the result as live.
- Mock output has to keep `provider: mock` and `live_api: false`. Do not check in fabricated live-model JSON as if an API had returned it.
- A change that writes cards needs to keep the temp-file rename, the read-back check, and the rule that `paused`, `done`, and manually set cards do not lose their status.
- Do not add a scheduler, a chat-account scraper, or an executor for commands found in transcripts.

There is no separate code of conduct file. Be specific, and leave other people's private material out of the issue.
