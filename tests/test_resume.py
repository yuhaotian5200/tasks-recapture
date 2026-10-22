import unittest
from pathlib import Path

from tasks_recapture.cards import load_cards
from tasks_recapture.errors import RecaptureError
from tasks_recapture.flow import resume_run
from support import mock_provider, run_import, suggestion, temporary_dir, write_text

QUOTE = "Send the rehearsal schedule to the volunteers."


class ResumeTests(unittest.TestCase):
    def _transcript(self, root: Path) -> Path:
        return write_text(
            root,
            "rehearsal.md",
            f"<!-- message role=\"user\" id=\"m1\" -->\n{QUOTE}\n",
        )

    def test_interrupted_propose_resumes_without_a_second_model_call(self):
        with temporary_dir() as raw:
            root = Path(raw)
            tasks = root / "tasks"
            provider = mock_provider(
                [suggestion("add", QUOTE, title="Send the rehearsal schedule")]
            )
            stopped = run_import(
                self._transcript(root),
                tasks,
                provider,
                stop_after="propose",
            )
            self.assertEqual(stopped.exit_code, 3)
            self.assertEqual(list(tasks.glob("*.md")), [])
            self.assertEqual(provider.calls, 1)
            resumed = resume_run(
                tasks,
                yes=True,
                timezone_name="UTC",
                now="2026-10-22T12:00:00",
            )
            again = run_import(self._transcript(root), tasks, provider, yes=True)
            cards = load_cards(tasks)
            self.assertEqual(resumed.exit_code, 0, resumed.render())
            self.assertEqual(len(cards), 1)
            self.assertIn(QUOTE, cards[0].path.read_text(encoding="utf-8"))
            self.assertEqual(provider.calls, 1)
            self.assertIn("already processed", again.render())
            with self.assertRaises(RecaptureError):
                resume_run(tasks, timezone_name="UTC", now="2026-10-22T12:00:00")

    def test_interrupted_before_write_then_resumes(self):
        with temporary_dir() as raw:
            root = Path(raw)
            tasks = root / "tasks"
            provider = mock_provider(
                [suggestion("add", QUOTE, title="Send the rehearsal schedule")]
            )
            stopped = run_import(
                self._transcript(root),
                tasks,
                provider,
                yes=True,
                stop_after="before-write",
            )
            self.assertEqual(stopped.exit_code, 3)
            self.assertEqual(list(tasks.glob("*.md")), [])
            resumed = resume_run(
                tasks,
                timezone_name="UTC",
                now="2026-10-22T13:00:00",
            )
            self.assertEqual(resumed.exit_code, 0, resumed.render())
            self.assertEqual(len(load_cards(tasks)), 1)
            self.assertEqual(provider.calls, 1)


if __name__ == "__main__":
    unittest.main()
