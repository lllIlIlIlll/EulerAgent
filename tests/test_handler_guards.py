"""Contract: /session.* runtime-tuning whitelist (P0 hardening) + working-memory folding."""
import queue, types, unittest
import _bootstrap  # noqa: F401
import agentmain
from ea import EulerAgentHandler


class TestSlashWhitelist(unittest.TestCase):
    def _call(self, raw):
        fake = types.SimpleNamespace(llmclient=types.SimpleNamespace(backend=types.SimpleNamespace()))
        q = queue.Queue()
        return agentmain.EulerAgent._handle_slash_cmd(fake, raw, q), fake, q

    def test_non_slash_passthrough(self):
        r, _, _ = self._call('hello')
        self.assertEqual(r, 'hello')

    def test_blocked_key_rejected(self):
        r, fake, q = self._call('/session.api_key=sk-evil')
        self.assertIsNone(r)
        self.assertIn('不允许', q.get_nowait()['done'])
        self.assertFalse(hasattr(fake.llmclient.backend, 'api_key'))

    def test_allowed_key_parses_json_value(self):
        r, fake, _ = self._call('/session.temperature=0.5')
        self.assertIsNone(r)
        self.assertEqual(fake.llmclient.backend.temperature, 0.5)


class TestFoldEarlier(unittest.TestCase):
    def test_folds_agent_turns_between_users(self):
        h = EulerAgentHandler(types.SimpleNamespace())
        folded = h._fold_earlier(['[USER]: q1', '[Agent] a', '[Agent] b', '[USER]: q2', '[Agent] c'])
        self.assertIn('[USER]: q1', folded)
        self.assertIn('[Agent] b（2 turns）', folded)
        self.assertIn('[Agent] c（1 turns）', folded)


if __name__ == "__main__":
    unittest.main()
