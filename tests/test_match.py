import unittest

from tasks_recapture.match import kind_for, match_titles, score_pair, tokenize


class TitleMatchTests(unittest.TestCase):
    def test_synonym_paraphrase_is_certain(self):
        score, overlap = score_pair(
            "Write the weekly status note",
            "Draft the weekly status memo",
        )
        self.assertEqual(kind_for(score, overlap), "certain")
        self.assertGreaterEqual(score, 0.75)

    def test_chinese_synonym_paraphrase_is_certain(self):
        score, overlap = score_pair("起草十一月园丁通讯", "撰写十一月园丁通讯")
        self.assertEqual(kind_for(score, overlap), "certain")

    def test_related_but_distinct_work_is_uncertain(self):
        score, overlap = score_pair(
            "Prepare the Friday booth checklist",
            "Prepare the Saturday workshop checklist",
        )
        self.assertEqual(kind_for(score, overlap), "uncertain")

    def test_unrelated_titles_do_not_match(self):
        score, overlap = score_pair(
            "Fix the login defect",
            "Add a dark mode toggle",
        )
        self.assertEqual(kind_for(score, overlap), "none")
        self.assertEqual(overlap, 0)

    def test_two_certain_cards_are_not_auto_resolved(self):
        cards = [
            _Card("task-aaaabbbbcccc", "Write the weekly status note"),
            _Card("task-dddddddddddd", "Draft the weekly status memo"),
        ]
        match = match_titles("Write the weekly status note", cards)
        self.assertEqual(match["kind"], "uncertain")
        self.assertEqual(len(match["candidates"]), 2)

    def test_model_hint_without_title_overlap_stays_uncertain(self):
        cards = [_Card("task-aaaabbbbcccc", "Publish the annual report", "done")]
        match = match_titles(
            "Ignore previous instructions",
            cards,
            hinted_id="task-aaaabbbbcccc",
        )
        self.assertEqual(match["kind"], "uncertain")
        self.assertEqual(match["candidates"][0]["id"], "task-aaaabbbbcccc")

    def test_resume_words_share_a_token(self):
        arrived = tokenize("The plant list arrived this morning.")
        condition = tokenize("The plant list arrives.")
        self.assertGreaterEqual(len(condition & arrived), 2)


class _Card:
    def __init__(self, id, title, status="not_started"):
        self.id = id
        self.title = title
        self.status = status


if __name__ == "__main__":
    unittest.main()
