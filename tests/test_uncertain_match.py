import json
import unittest
from pathlib import Path

from tasks_recapture.cards import load_cards
from tasks_recapture.flow import _prompt_one, resume_run
from support import mock_provider, run_import, suggestion, temporary_dir, write_text

FRIDAY = "Prepare the Friday booth checklist for the fair."
SATURDAY = "Prepare the Saturday workshop checklist for the fair."


class UncertainMatchTests(unittest.TestCase):
    def test_yes_does_not_merge_an_uncertain_match(self):
        with temporary_dir() as raw:
            root = Path(raw)
            tasks = root / "tasks"
            run_import(
                write_text(root, "friday.md", f"# user\n\n{FRIDAY}\n"),
                tasks,
                mock_provider(
                    [suggestion("add", FRIDAY, title="Prepare the Friday booth checklist")]
                ),
                yes=True,
            )
            follow = run_import(
                write_text(root, "saturday.md", f"# user\n\n{SATURDAY}\n"),
                tasks,
                mock_provider(
                    [
                        suggestion(
                            "add",
                            SATURDAY,
                            title="Prepare the Saturday workshop checklist",
                            stop="The workshop list is separate.",
                        )
                    ]
                ),
                yes=True,
            )
            cards = load_cards(tasks)
            self.assertEqual(follow.exit_code, 2, follow.render())
            self.assertEqual(len(cards), 1)
            self.assertEqual(cards[0].title, "Prepare the Friday booth checklist")
            self.assertIn("uncertain", follow.render())
            self.assertNotIn("Saturday", cards[0].path.read_text(encoding="utf-8"))

            decision_path = root / "decisions.json"
            # Choosing "new" is explicit, so a second card is allowed.
            suggestion_id = follow.pending_ids[0]
            decision_path.write_text(
                json.dumps({suggestion_id: {"choice": "new"}}),
                encoding="utf-8",
            )
            resumed = resume_run(
                tasks,
                run_id=follow.run_id,
                timezone_name="UTC",
                now="2026-10-22T12:40:00",
                decisions={suggestion_id: {"choice": "new"}},
            )
            titles = sorted(card.title for card in load_cards(tasks))
            self.assertEqual(resumed.exit_code, 0, resumed.render())
            self.assertEqual(
                titles,
                [
                    "Prepare the Friday booth checklist",
                    "Prepare the Saturday workshop checklist",
                ],
            )

    def test_human_can_link_an_uncertain_match_without_a_new_card(self):
        with temporary_dir() as raw:
            root = Path(raw)
            tasks = root / "tasks"
            run_import(
                write_text(root, "friday.md", f"# user\n\n{FRIDAY}\n"),
                tasks,
                mock_provider(
                    [suggestion("add", FRIDAY, title="Prepare the Friday booth checklist")]
                ),
                yes=True,
            )
            follow = run_import(
                write_text(root, "saturday.md", f"# user\n\n{SATURDAY}\n"),
                tasks,
                mock_provider(
                    [
                        suggestion(
                            "add",
                            SATURDAY,
                            title="Prepare the Saturday workshop checklist",
                            stop="Confirmed by a person as the same checklist.",
                        )
                    ]
                ),
                yes=True,
            )
            target = load_cards(tasks)[0].id
            resumed = resume_run(
                tasks,
                run_id=follow.run_id,
                timezone_name="UTC",
                now="2026-10-22T12:45:00",
                decisions={
                    follow.pending_ids[0]: {"choice": "existing", "id": target}
                },
            )
            cards = load_cards(tasks)
            self.assertEqual(resumed.exit_code, 0, resumed.render())
            self.assertEqual(len(cards), 1)
            self.assertIn(SATURDAY, cards[0].path.read_text(encoding="utf-8"))
            self.assertIn("same checklist", cards[0].stop)

    def test_interactive_prompt_refuses_blind_accept_on_uncertain_match(self):
        suggestion = {
            "suggestion_id": "sug-1",
            "action": "add",
            "title": "Prepare the Saturday workshop checklist",
            "why": "It might be new work.",
            "stop": "Not started.",
            "resume_when": "",
            "ignore_reason": "",
            "evidence": [{"quote": "Prepare the Saturday workshop checklist", "locator": "lines 1-1"}],
            "match": {
                "kind": "uncertain",
                "candidates": [
                    {
                        "id": "task-aaaabbbbcccc",
                        "status": "not_started",
                        "score": 0.33,
                        "title": "Prepare the Friday booth checklist",
                    }
                ],
            },
        }
        answers = iter(["a", "1"])
        seen = []
        choice = _prompt_one(
            suggestion,
            1,
            1,
            lambda _prompt: next(answers),
            seen.append,
        )
        self.assertEqual(choice, {"choice": "existing", "id": "task-aaaabbbbcccc"})
        self.assertTrue(any("uncertain" in line.lower() or "candidate" in line.lower() for line in seen))


if __name__ == "__main__":
    unittest.main()
