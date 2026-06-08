"""Contract: SSE parsers (_parse_claude_sse / _parse_openai_sse).
Feeds a fixed byte stream, asserts yielded text + returned content_blocks."""
import unittest
from _bootstrap import drive
import llmcore

def lines(*items): return [s.encode("utf-8") for s in items]

class TestClaudeSSE(unittest.TestCase):
    def test_text_then_tool_use(self):
        stream = lines(
            'data: {"type":"message_start","message":{"usage":{}}}',
            'data: {"type":"content_block_start","content_block":{"type":"text"}}',
            'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Hello"}}',
            'data: {"type":"content_block_stop"}',
            'data: {"type":"content_block_start","content_block":{"type":"tool_use","id":"t1","name":"foo"}}',
            'data: {"type":"content_block_delta","delta":{"type":"input_json_delta","partial_json":"{\\"x\\":1}"}}',
            'data: {"type":"content_block_stop"}',
            'data: {"type":"message_stop"}',
            'data: [DONE]',
        )
        yields, blocks = drive(llmcore._parse_claude_sse(stream))
        self.assertEqual("".join(yields), "Hello")
        self.assertEqual(blocks[0], {"type": "text", "text": "Hello"})
        self.assertEqual(blocks[1], {"type": "tool_use", "id": "t1", "name": "foo", "input": {"x": 1}})

class TestOpenAISSE(unittest.TestCase):
    def test_chat_completions_text_and_tool(self):
        stream = lines(
            'data: {"choices":[{"delta":{"content":"Hello"}}]}',
            'data: {"choices":[{"delta":{"content":" world"}}]}',
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1","function":{"name":"foo","arguments":"{\\"x\\":1}"}}]}}]}',
            'data: [DONE]',
        )
        yields, blocks = drive(llmcore._parse_openai_sse(stream, api_mode="chat_completions"))
        self.assertEqual("".join(yields), "Hello world")
        self.assertEqual(blocks[0], {"type": "text", "text": "Hello world"})
        self.assertEqual(blocks[1], {"type": "tool_use", "id": "c1", "name": "foo", "input": {"x": 1}})

    def test_malformed_data_line_is_skipped(self):
        stream = lines(
            'data: {not json}',
            'data: {"choices":[{"delta":{"content":"ok"}}]}',
            'data: [DONE]',
        )
        yields, blocks = drive(llmcore._parse_openai_sse(stream, api_mode="chat_completions"))
        self.assertEqual("".join(yields), "ok")

if __name__ == "__main__":
    unittest.main()
