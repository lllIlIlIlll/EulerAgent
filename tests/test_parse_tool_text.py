"""Contract: _parse_text_tool_calls — the text-fallback tool extractor.
This is the compatibility regression net the PR-A2 narrowing flagged."""
import json, unittest
import _bootstrap  # noqa: F401
import llmcore

def first(tcs):
    tc = tcs[0]
    return tc.function.name, json.loads(tc.function.arguments)

class TestParseToolText(unittest.TestCase):
    def test_xml_tag(self):
        tcs, rest = llmcore._parse_text_tool_calls('<tool_use>{"name": "foo", "arguments": {"x": 1}}</tool_use>')
        self.assertEqual(first(tcs), ("foo", {"x": 1}))
        self.assertEqual(rest, "")

    def test_json_array(self):
        tcs, rest = llmcore._parse_text_tool_calls('[{"type":"tool_use","name":"bar","input":{"y":2}}]')
        self.assertEqual(first(tcs), ("bar", {"y": 2}))

    def test_plain_text_yields_no_calls(self):
        tcs, rest = llmcore._parse_text_tool_calls("just a normal reply, no tools here")
        self.assertEqual(tcs, [])
        self.assertEqual(rest, "just a normal reply, no tools here")

class TestTryparse(unittest.TestCase):
    def test_strips_markdown_fence(self):
        self.assertEqual(llmcore.tryparse('```json\n{"a": 1}'), {"a": 1})

    def test_trailing_garbage_after_brace(self):
        self.assertEqual(llmcore.tryparse('{"a": 1} trailing'), {"a": 1})

if __name__ == "__main__":
    unittest.main()
