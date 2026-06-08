"""Contract: model_caps capability table (D4). Locks behaviour against drift after
converging the scattered deepseek/kimi/minimax/gpt-5 special-cases into one table."""
import unittest
import _bootstrap  # noqa: F401
import llmcore

class TestModelCaps(unittest.TestCase):
    def test_default_family(self):
        c = llmcore.model_caps("gpt-4o")
        self.assertEqual((c["context_win"], c["cut_msg_interval"], c["trim_keep_rate"]), (30000, 5, 0.6))
        self.assertFalse(c["keep_thinking"])
        self.assertIsNone(c["temperature_override"])
        self.assertIsNone(c["temperature_clamp"])
        self.assertEqual(c["max_tokens_field"], "max_tokens")

    def test_deepseek(self):
        c = llmcore.model_caps("deepseek-chat")
        self.assertEqual((c["context_win"], c["cut_msg_interval"], c["trim_keep_rate"]), (70000, 25, 0.3))
        self.assertTrue(c["keep_thinking"])

    def test_kimi_and_moonshot_force_temp(self):
        self.assertEqual(llmcore.model_caps("kimi-k2")["temperature_override"], 1)
        self.assertEqual(llmcore.model_caps("moonshot-v1")["temperature_override"], 1)

    def test_minimax_clamps_temp(self):
        self.assertEqual(llmcore.model_caps("minimax-abab")["temperature_clamp"], (0.01, 1.0))

    def test_reasoning_models_use_max_completion_tokens(self):
        for m in ("gpt-5", "o1-preview", "o3-mini", "o4"):
            self.assertEqual(llmcore.model_caps(m)["max_tokens_field"], "max_completion_tokens", m)
        self.assertEqual(llmcore.model_caps("gpt-4-turbo")["max_tokens_field"], "max_tokens")

    def test_session_applies_table(self):
        cfg = {"apikey": "k", "apibase": "https://x/v1", "model": "deepseek-chat"}
        sess = llmcore.BaseSession(cfg)
        self.assertEqual((sess.cut_msg_interval, sess.trim_keep_rate, sess.context_win), (25, 0.3, 70000))
        self.assertTrue(sess.keep_thinking)
        plain = llmcore.BaseSession({"apikey": "k", "apibase": "https://x/v1", "model": "gpt-4o"})
        self.assertEqual((plain.cut_msg_interval, plain.trim_keep_rate, plain.context_win), (5, 0.6, 30000))

if __name__ == "__main__":
    unittest.main()
