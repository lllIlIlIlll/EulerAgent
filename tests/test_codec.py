"""Contract: protocol codecs (_msgs_claude2oai / _to_responses_input / _fix_messages).
Locks the most fragile part of the planned llmcore split."""
import json, unittest
import _bootstrap  # noqa: F401  (sys.path side effect)
import llmcore

CLAUDE_HISTORY = [
    {"role": "user", "content": [{"type": "text", "text": "hi"}]},
    {"role": "assistant", "content": [
        {"type": "thinking", "thinking": "hmm"},
        {"type": "text", "text": "hello"},
        {"type": "tool_use", "id": "t1", "name": "foo", "input": {"x": 1}},
    ]},
    {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "42"}]},
]

class TestClaudeToOAI(unittest.TestCase):
    def test_roundtrip_shape(self):
        oai = llmcore._msgs_claude2oai(CLAUDE_HISTORY)
        self.assertEqual([m.get("role") for m in oai], ["user", "assistant", "tool"])
        asst = oai[1]
        self.assertEqual(asst["reasoning_content"], "hmm")
        self.assertEqual(asst["content"], [{"type": "text", "text": "hello"}])
        self.assertEqual(asst["tool_calls"][0]["function"]["name"], "foo")
        self.assertEqual(json.loads(asst["tool_calls"][0]["function"]["arguments"]), {"x": 1})
        self.assertEqual(oai[2], {"role": "tool", "tool_call_id": "t1", "content": "42"})

    def test_assistant_with_only_tool_use_gets_no_dot_filler(self):
        oai = llmcore._msgs_claude2oai([
            {"role": "assistant", "content": [{"type": "tool_use", "id": "a", "name": "f", "input": {}}]},
        ])
        self.assertNotIn("content", oai[0])
        self.assertIn("tool_calls", oai[0])

class TestToResponsesInput(unittest.TestCase):
    def test_chain_from_oai(self):
        responses = llmcore._to_responses_input(llmcore._msgs_claude2oai(CLAUDE_HISTORY))
        self.assertEqual(responses[0], {"role": "user", "content": [{"type": "input_text", "text": "hi"}]})
        self.assertEqual(responses[1], {"role": "assistant", "content": [{"type": "output_text", "text": "hello"}]})
        fc = responses[2]
        self.assertEqual((fc["type"], fc["call_id"], fc["name"]), ("function_call", "t1", "foo"))
        self.assertEqual(responses[3], {"type": "function_call_output", "call_id": "t1", "output": "42"})

class TestFixMessages(unittest.TestCase):
    def test_merges_consecutive_same_role(self):
        fixed = llmcore._fix_messages([
            {"role": "user", "content": "A"},
            {"role": "user", "content": "B"},
        ])
        self.assertEqual(len(fixed), 1)
        self.assertEqual([b["text"] for b in fixed[0]["content"]], ["A", "\n", "B"])

    def test_injects_missing_tool_result(self):
        fixed = llmcore._fix_messages([
            {"role": "user", "content": "start"},
            {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "f", "input": {}}]},
            {"role": "user", "content": [{"type": "text", "text": "ok"}]},
        ])
        self.assertEqual(fixed[2]["content"][0],
                         {"type": "tool_result", "tool_use_id": "t1", "content": "(error)"})

    def test_downgrades_orphan_tool_result(self):
        fixed = llmcore._fix_messages([
            {"role": "user", "content": "s"},
            {"role": "assistant", "content": [{"type": "text", "text": "hi"}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "x", "content": "r"}]},
        ])
        types = [b.get("type") for b in fixed[2]["content"]]
        self.assertNotIn("tool_result", types)
        self.assertEqual(fixed[2]["content"][0], {"type": "text", "text": "r"})

    def test_drops_leading_non_user(self):
        fixed = llmcore._fix_messages([
            {"role": "assistant", "content": "lead"},
            {"role": "user", "content": "u"},
        ])
        self.assertTrue(fixed[0]["role"] == "user")

if __name__ == "__main__":
    unittest.main()
