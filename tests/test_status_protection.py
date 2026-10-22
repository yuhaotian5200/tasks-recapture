import unittest
from pathlib import Path

from tasks_recapture.cards import load_cards
from tasks_recapture.flow import mark_status
from support import mock_provider, run_import, suggestion, temporary_dir, write_text


def _card_text(tasks: Path, title: str) -> str:
    card = next(card for card in load_cards(tasks) if card.title == title)
    return card.path.read_text(encoding="utf-8")


class StatusProtectionTests(unittest.TestCase):
    def test_done_paused_and_manual_status_are_not_overwritten(self):
        with temporary_dir() as raw:
            root = Path(raw)
            tasks = root / "tasks"
            report_quote = "Publish the annual report for the members."
            hold_quote = "Let's draft the November garden newsletter once the plant list arrives."
            manual_quote = "Sketch the welcome sign for the gate."
            run_import(
                write_text(root, "report.md", f"# user\n\n{report_quote}\n"),
                tasks,
                mock_provider(
                    [suggestion("add", report_quote, title="Publish the annual report")]
                ),
                yes=True,
            )
            run_import(
                write_text(root, "news.md", f"# user\n\n{hold_quote}\n"),
                tasks,
                mock_provider(
                    [
                        suggestion(
                            "add",
                            hold_quote,
                            title="Draft the November garden newsletter",
                            proposed_status="paused",
                            resume_when="The plant list arrives.",
                            stop="The draft is waiting on the plant list.",
                        )
                    ]
                ),
                yes=True,
            )
            run_import(
                write_text(root, "sign.md", f"# user\n\n{manual_quote}\n"),
                tasks,
                mock_provider(
                    [suggestion("add", manual_quote, title="Sketch the welcome sign")]
                ),
                yes=True,
            )
            by_title = {card.title: card for card in load_cards(tasks)}
            mark_status(
                tasks,
                by_title["Publish the annual report"].id,
                "done",
                timezone_name="UTC",
                now="2026-10-22T12:10:00",
            )
            mark_status(
                tasks,
                by_title["Sketch the welcome sign"].id,
                "not_started",
                timezone_name="UTC",
                now="2026-10-22T12:11:00",
            )

            later_report = "Please publish the annual report again from scratch."
            later_news = "Please write the November garden newsletter tonight."
            later_sign = "Please sketch the welcome sign in neon paint."
            run_import(
                write_text(root, "report-2.md", f"# user\n\n{later_report}\n"),
                tasks,
                mock_provider(
                    [
                        suggestion(
                            "update",
                            later_report,
                            title="Publish the annual report",
                            proposed_status="in_progress",
                            stop="Reopen the report and start over.",
                            existing_id=by_title["Publish the annual report"].id,
                        )
                    ]
                ),
                yes=True,
            )
            run_import(
                write_text(root, "news-2.md", f"# user\n\n{later_news}\n"),
                tasks,
                mock_provider(
                    [
                        suggestion(
                            "add",
                            later_news,
                            title="Write the November garden newsletter",
                            proposed_status="in_progress",
                            stop="Start the draft tonight.",
                            resume_when="",
                        )
                    ]
                ),
                yes=True,
            )
            run_import(
                write_text(root, "sign-2.md", f"# user\n\n{later_sign}\n"),
                tasks,
                mock_provider(
                    [
                        suggestion(
                            "update",
                            later_sign,
                            title="Sketch the welcome sign",
                            proposed_status="in_progress",
                            stop="Switch the sketch to neon paint.",
                        )
                    ]
                ),
                yes=True,
            )
            cards = {card.title: card for card in load_cards(tasks)}
            self.assertEqual(len(cards), 3)
            report = cards["Publish the annual report"]
            news = cards["Draft the November garden newsletter"]
            sign = cards["Sketch the welcome sign"]
            self.assertEqual(report.status, "done")
            self.assertEqual(report.stop, "It has not been started.")
            self.assertNotIn("start over", report.stop.lower())
            self.assertEqual(news.status, "paused")
            self.assertEqual(news.resume_when, "The plant list arrives.")
            self.assertNotIn("tonight", news.stop.lower())
            self.assertEqual(sign.status, "not_started")
            self.assertTrue(sign.manual)
            self.assertEqual(sign.stop, "It has not been started.")
            self.assertNotIn("neon", sign.stop.lower())
            for card in (report, news, sign):
                text = card.path.read_text(encoding="utf-8")
                self.assertIn("**authorization:** record_only", text)
                self.assertIn("does not authorize", text)
                self.assertIn("were kept", text)

    def test_explicit_link_still_cannot_reopen_a_done_card(self):
        with temporary_dir() as raw:
            root = Path(raw)
            tasks = root / "tasks"
            quote = "File the annual report with the secretary."
            created = run_import(
                write_text(root, "one.md", f"# user\n\n{quote}\n"),
                tasks,
                mock_provider([suggestion("add", quote, title="File the annual report")]),
                yes=True,
            )
            self.assertEqual(created.exit_code, 0)
            card = load_cards(tasks)[0]
            mark_status(tasks, card.id, "done", timezone_name="UTC", now="2026-10-22T12:20:00")
            other = "Buy paint for the fence."
            stopped = run_import(
                write_text(root, "two.md", f"# user\n\n{other}\n"),
                tasks,
                mock_provider(
                    [
                        suggestion(
                            "update",
                            other,
                            title="Buy paint for the fence",
                            proposed_status="in_progress",
                            stop="Treat the report as open.",
                            existing_id=card.id,
                        )
                    ]
                ),
                stop_after="propose",
            )
            suggestion_id = None
            # The proposal is stored on the run; resume with an explicit link.
            from tasks_recapture.flow import _read_json, _run_path

            run = _read_json(_run_path(tasks, stopped.run_id), {})
            suggestion_id = run["suggestions"][0]["suggestion_id"]
            self.assertEqual(run["suggestions"][0]["match"]["kind"], "uncertain")
            resumed = __import__(
                "tasks_recapture.flow", fromlist=["resume_run"]
            ).resume_run(
                tasks,
                run_id=stopped.run_id,
                timezone_name="UTC",
                now="2026-10-22T12:30:00",
                decisions={suggestion_id: {"choice": "existing", "id": card.id}},
            )
            self.assertEqual(resumed.exit_code, 0, resumed.render())
            final = load_cards(tasks)[0]
            self.assertEqual(len(load_cards(tasks)), 1)
            self.assertEqual(final.status, "done")
            self.assertNotIn("Treat the report as open", final.stop)


if __name__ == "__main__":
    unittest.main()
