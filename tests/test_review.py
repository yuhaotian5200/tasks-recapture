import unittest
from pathlib import Path

from tasks_recapture.cards import load_cards
from tasks_recapture.flow import review_cards
from tasks_recapture.store import sha256_text
from support import mock_provider, run_import, suggestion, temporary_dir, write_text


class ReviewTests(unittest.TestCase):
    def test_new_material_can_match_a_resume_condition_without_editing(self):
        with temporary_dir() as raw:
            root = Path(raw)
            tasks = root / "tasks"
            quote = "Let's draft the November garden newsletter once the plant list arrives."
            run_import(
                write_text(root, "first.md", f"# user\n\n{quote}\n"),
                tasks,
                mock_provider(
                    [
                        suggestion(
                            "add",
                            quote,
                            title="Draft the November garden newsletter",
                            proposed_status="paused",
                            resume_when="The plant list arrives.",
                            stop="Waiting on the plant list.",
                        )
                    ]
                ),
                yes=True,
            )
            follow = write_text(
                root,
                "follow.md",
                "# user\n\nThe plant list arrived this morning.\n",
            )
            before = {
                card.path: sha256_text(card.path.read_text(encoding="utf-8"))
                for card in load_cards(tasks)
            }
            hints = review_cards(tasks, follow)
            after = {
                card.path: sha256_text(card.path.read_text(encoding="utf-8"))
                for card in load_cards(tasks)
            }
            self.assertEqual(before, after)
            self.assertEqual(len(hints), 1)
            self.assertTrue(hints[0]["status_unchanged"])
            self.assertEqual(hints[0]["status"], "paused")
            self.assertIn("not changed", hints[0]["message"])
            self.assertIn("plant", hints[0]["overlap"])


if __name__ == "__main__":
    unittest.main()
