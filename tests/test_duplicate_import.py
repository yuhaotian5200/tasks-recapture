import unittest
from pathlib import Path

from tasks_recapture.cards import load_cards
from tasks_recapture.flow import resume_run
from support import mock_provider, run_import, suggestion, temporary_dir, write_text

QUOTE = "Write the weekly status note before Monday."


class DuplicateImportTests(unittest.TestCase):
    def test_same_transcript_does_not_create_a_second_card(self):
        with temporary_dir() as raw:
            root = Path(raw)
            tasks = root / "tasks"
            transcript = write_text(
                root,
                "weekly.md",
                f"<!-- message role=\"user\" id=\"m1\" -->\n{QUOTE}\n",
            )
            provider = mock_provider(
                [suggestion("add", QUOTE, title="Write the weekly status note")]
            )
            first = run_import(transcript, tasks, provider, yes=True)
            second = run_import(transcript, tasks, provider, yes=True)
            cards = load_cards(tasks)
            self.assertEqual(first.exit_code, 0)
            self.assertEqual(second.exit_code, 0)
            self.assertEqual(provider.calls, 1)
            self.assertEqual(len(cards), 1)
            self.assertIn("already processed", second.render())
            self.assertFalse(second.live_api)
            self.assertEqual(second.provider, "mock")
            self.assertNotIn("live-api", cards[0].path.read_text(encoding="utf-8"))

    def test_synonym_in_a_later_transcript_reconnects(self):
        with temporary_dir() as raw:
            root = Path(raw)
            tasks = root / "tasks"
            first_quote = "Please write the weekly status note."
            second_quote = "Please draft the weekly status memo."
            first_path = write_text(root, "one.md", f"# user\n\n{first_quote}\n")
            second_path = write_text(root, "two.md", f"# user\n\n{second_quote}\n")
            first_provider = mock_provider(
                [suggestion("add", first_quote, title="Write the weekly status note")]
            )
            second_provider = mock_provider(
                [
                    suggestion(
                        "add",
                        second_quote,
                        title="Draft the weekly status memo",
                        stop="The note still needs the Monday figures.",
                    )
                ]
            )
            run_import(first_path, tasks, first_provider, yes=True)
            follow = run_import(second_path, tasks, second_provider, yes=True)
            cards = load_cards(tasks)
            self.assertEqual(follow.exit_code, 0)
            self.assertEqual(len(cards), 1)
            text = cards[0].path.read_text(encoding="utf-8")
            self.assertIn("Write the weekly status note", text)
            self.assertIn(second_quote, text)
            self.assertIn("Monday figures", text)
            self.assertEqual(cards[0].status, "not_started")

    def test_plain_text_keeps_unknown_role_and_hides_absolute_path(self):
        with temporary_dir() as raw:
            root = Path(raw) / "secret-home-name"
            root.mkdir()
            tasks = root / "tasks"
            quote = "Collect the stall layout from the organizer."
            path = write_text(root, "notes.txt", quote + "\n")
            provider = mock_provider(
                [suggestion("add", quote, title="Collect the stall layout")]
            )
            result = run_import(path, tasks, provider, yes=True)
            text = load_cards(tasks)[0].path.read_text(encoding="utf-8")
            self.assertEqual(result.exit_code, 0)
            self.assertIn("role: unknown", text)
            self.assertIn("notes.txt", text)
            self.assertNotIn("secret-home-name", text)
            self.assertNotIn(str(path.parent), text)

    def test_duplicate_titles_in_one_response_make_one_card(self):
        with temporary_dir() as raw:
            root = Path(raw)
            tasks = root / "tasks"
            first = "Order the seedling trays this week."
            second = "Order the seedling trays before the sale."
            transcript = write_text(
                root,
                "trays.md",
                f"# user\n\n{first}\n\n{second}\n",
            )
            provider = mock_provider(
                [
                    suggestion("add", first, title="Order the seedling trays"),
                    suggestion("add", second, title="Order the seedling trays"),
                ]
            )
            result = run_import(transcript, tasks, provider, yes=True)
            cards = load_cards(tasks)
            self.assertEqual(result.exit_code, 0, result.render())
            self.assertEqual(len(cards), 1)
            text = cards[0].path.read_text(encoding="utf-8")
            self.assertIn(first, text)
            self.assertIn(second, text)


if __name__ == "__main__":
    unittest.main()
