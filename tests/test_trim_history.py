"""Contract: trim_messages_history — over-budget history shrinks, first msg stays user."""
import unittest
import _bootstrap  # noqa: F401
import llmcore

class FakeSess:
    context_win = 50          # cap = 150 chars, target = 75
    trim_keep_rate = 0.5
    cut_msg_interval = 1

class TestTrimHistory(unittest.TestCase):
    def _big_history(self, n=20):
        out = []
        for i in range(n):
            role = "user" if i % 2 == 0 else "assistant"
            out.append({"role": role, "content": [{"type": "text", "text": "x" * 200}]})
        return out

    def test_over_budget_is_trimmed_and_starts_with_user(self):
        hist = self._big_history()
        original = len(hist)
        llmcore.trim_messages_history(hist, FakeSess())
        self.assertLess(len(hist), original)
        self.assertEqual(hist[0]["role"], "user")

    def test_under_budget_is_untouched(self):
        hist = [{"role": "user", "content": [{"type": "text", "text": "tiny"}]}]
        llmcore.trim_messages_history(hist, FakeSess())
        self.assertEqual(len(hist), 1)

if __name__ == "__main__":
    unittest.main()
