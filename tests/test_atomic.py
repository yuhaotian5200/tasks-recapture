import unittest
from pathlib import Path

from tasks_recapture.cards import load_cards
from tasks_recapture.errors import ConflictError, StoreError
from tasks_recapture.flow import resume_run
from tasks_recapture.store import atomic_write, sha256_text
from support import mock_provider, run_import, suggestion, temporary_dir, write_text

QUOTE = "Reserve the practice room for Thursday."
FOLLOW = "Reserve the practice room and bring the key."


class AtomicWriteTests(unittest.TestCase):
    def test_replace_then_read_back(self):
        with temporary_dir() as raw:
            path = Path(raw) / "card.md"
            digest = atomic_write(path, "hello\n", None)
            self.assertEqual(path.read_text(encoding="utf-8"), "hello\n")
            self.assertEqual(digest, sha256_text("hello\n"))
            with self.assertRaises(ConflictError):
                atomic_write(path, "changed\n", "0" * 64)
            self.assertEqual(path.read_text(encoding="utf-8"), "hello\n")

    def test_conflict_keeps_the_newer_card_and_asks_again(self):
        with temporary_dir() as raw:
            root = Path(raw)
            tasks = root / "tasks"
            run_import(
                write_text(root, "one.md", f"# user\n\n{QUOTE}\n"),
                tasks,
                mock_provider([suggestion("add", QUOTE, title="Reserve the practice room")]),
                yes=True,
            )
            follow = run_import(
                write_text(root, "two.md", f"# user\n\n{FOLLOW}\n"),
                tasks,
                mock_provider(
                    [
                        suggestion(
                            "update",
                            FOLLOW,
                            title="Reserve the practice room",
                            stop="Bring the spare key.",
                        )
                    ]
                ),
                stop_after="propose",
            )
            card = load_cards(tasks)[0]
            original = card.path.read_text(encoding="utf-8")
            edited = original.replace(
                "It has not been started.",
                "USER-EDIT-MARKER kept by the person.",
            )
            card.path.write_text(edited, encoding="utf-8")
            resumed = resume_run(
                tasks,
                run_id=follow.run_id,
                yes=True,
                timezone_name="UTC",
                now="2026-10-22T15:00:00",
            )
            current = card.path.read_text(encoding="utf-8")
            self.assertEqual(resumed.exit_code, 2, resumed.render())
            self.assertIn("USER-EDIT-MARKER", current)
            self.assertIn("conflict", resumed.render())
            self.assertNotIn("Bring the spare key.", current)
            second = resume_run(
                tasks,
                run_id=follow.run_id,
                yes=True,
                timezone_name="UTC",
                now="2026-10-22T15:05:00",
            )
            self.assertEqual(second.exit_code, 2)
            self.assertIn("USER-EDIT-MARKER", card.path.read_text(encoding="utf-8"))

    def test_symlink_card_is_refused(self):
        with temporary_dir() as raw:
            root = Path(raw)
            tasks = root / "tasks"
            tasks.mkdir()
            outside = root / "outside.md"
            outside.write_text("outside\n", encoding="utf-8")
            (tasks / "linked.md").symlink_to(outside)
            with self.assertRaises(StoreError):
                load_cards(tasks)


if __name__ == "__main__":
    unittest.main()
