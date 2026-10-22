import os
import subprocess
import sys
import unittest
from pathlib import Path

from support import temporary_dir, write_text


class CliTests(unittest.TestCase):
    def test_cli_mock_flow_and_timezone(self):
        with temporary_dir() as raw:
            root = Path(raw)
            tasks = root / "tasks"
            quote = "Label the seed packets before the sale."
            transcript = write_text(root, "seeds.md", f"# user\n\n{quote}\n")
            script = root / "mock.json"
            script.write_text(
                """
                {
                  "provider": "openai-compatible",
                  "live_api": true,
                  "origin": "live-api",
                  "suggestions": [
                    {
                      "action": "add",
                      "title": "Label the seed packets",
                      "why": "The sale needs labeled packets.",
                      "stop": "The packets are not labeled yet.",
                      "resume_when": "",
                      "proposed_status": "not_started",
                      "evidence": [{"quote": "Label the seed packets before the sale."}]
                    }
                  ]
                }
                """.strip(),
                encoding="utf-8",
            )
            env = os.environ.copy()
            env["TASKS_RECAPTURE_API_KEY"] = "synthetic-key-should-not-leak"
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "tasks_recapture",
                    "import",
                    str(transcript),
                    "--tasks-dir",
                    str(tasks),
                    "--provider",
                    "mock",
                    "--mock-script",
                    str(script),
                    "--yes",
                    "--timezone",
                    "Asia/Taipei",
                    "--now",
                    "2026-10-22T12:00:00",
                ],
                check=False,
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertIn("provider: mock", completed.stdout)
            self.assertIn("live_api: false", completed.stdout)
            self.assertIn("origin: mock-script", completed.stdout)
            self.assertNotIn("synthetic-key-should-not-leak", completed.stdout)
            card = next(tasks.glob("*.md"))
            text = card.read_text(encoding="utf-8")
            self.assertIn("**status:** not_started", text)
            self.assertIn("+08:00", text)
            self.assertIn(quote, text)
            self.assertIn("suggestion_origin:** mock-script", text)
            self.assertNotIn("live-api", text)
            self.assertNotIn("synthetic-key-should-not-leak", text)
            listed = subprocess.run(
                [sys.executable, "-m", "tasks_recapture", "list", "--tasks-dir", str(tasks)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(listed.returncode, 0, listed.stderr)
            self.assertIn("Label the seed packets", listed.stdout)


if __name__ == "__main__":
    unittest.main()
