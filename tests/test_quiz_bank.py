import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCREENS = (ROOT / "web" / "screens.jsx").read_text(encoding="utf-8")


class QuizBankTests(unittest.TestCase):
    def test_each_local_role_restores_ten_stable_unique_questions(self):
        from tests.role_fixtures import frontend_profiles, load_frontend_roles
        profiles = frontend_profiles()
        bank = load_frontend_roles(profiles)['quizzes']
        self.assertEqual(bank, {p['id']: p['quiz'] for p in profiles})
        ids = [q['id'] for questions in bank.values() for q in questions]
        self.assertEqual(len(ids), 50)
        self.assertEqual(len(set(ids)), 50)
        for questions in bank.values():
            for question in questions:
                self.assertEqual(len(question['options']), 4)
                self.assertIn(question['answer'], range(4))

    def test_empty_library_and_role_without_quiz_have_no_builtin_questions(self):
        from tests.role_fixtures import frontend_profiles, load_frontend_roles
        self.assertEqual(load_frontend_roles([])['quizzes'], {})
        profile = frontend_profiles()[0]
        del profile['quiz']
        self.assertEqual(load_frontend_roles([profile])['quizzes'], {profile['id']: []})

    def test_progress_is_persistent_filtered_and_terminal(self):
        self.assertIn("sl_quiz_answered_", SCREENS)
        self.assertIn("Array.isArray", SCREENS)
        self.assertIn("JSON.stringify", SCREENS)
        self.assertIn("answeredQuizIds", SCREENS)
        self.assertIn("unansweredQuiz", SCREENS)
        self.assertIn("你已经答完关于 TA 的全部题目", SCREENS)
        self.assertIn("10 / 10", SCREENS)
        self.assertNotIn("for (let t = 0; t < 20; t++)", SCREENS)


from tests.role_fixtures import role_fixture_hooks
setUpModule, tearDownModule = role_fixture_hooks()


if __name__ == "__main__":
    unittest.main()
