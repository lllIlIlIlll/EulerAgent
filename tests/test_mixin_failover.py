"""Contract: MixinSession failover — error chunks swallowed, fallback switches _cur_idx,
exhausted retries surface the last error, spring-back returns to primary."""
import time, types, unittest
import _bootstrap  # noqa: F401
from _bootstrap import drive
import llmcore


def _fake(name, chunks):
    sess = types.SimpleNamespace(name=name, max_retries=4)
    def raw_ask(*a, **k):
        for c in chunks: yield c
        return []
    sess.raw_ask = raw_ask
    return types.SimpleNamespace(backend=sess)


class TestMixinFailover(unittest.TestCase):
    def test_error_session_falls_back_and_sticks(self):
        mix = llmcore.MixinSession([_fake('a', ['!!!Error: HTTP 500']), _fake('b', ['ok'])],
                                   {'llm_nos': [0, 1], 'max_retries': 2})
        out, _ = drive(mix.raw_ask())
        self.assertEqual(out, ['ok'])
        self.assertEqual(mix._cur_idx, 1)  # recovery sticks to working session

    def test_all_fail_surfaces_last_error(self):
        mix = llmcore.MixinSession([_fake('a', ['!!!Error: A']), _fake('b', ['!!!Error: B'])],
                                   {'llm_nos': [0, 1], 'max_retries': 1, 'base_delay': 0})
        out, _ = drive(mix.raw_ask())
        self.assertEqual(out, ['!!!Error: B'])

    def test_spring_back_to_primary(self):
        mix = llmcore.MixinSession([_fake('a', ['ok-a']), _fake('b', ['ok-b'])],
                                   {'llm_nos': [0, 1], 'spring_back': 0})
        mix._cur_idx = 1; mix._switched_at = time.time() - 1
        out, _ = drive(mix.raw_ask())
        self.assertEqual(out, ['ok-a'])
        self.assertEqual(mix._cur_idx, 0)


if __name__ == "__main__":
    unittest.main()
