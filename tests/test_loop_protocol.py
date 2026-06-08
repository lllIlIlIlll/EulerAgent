"""Contract: agent_runner_loop — StepOutcome flow, no_tool routing, exit reasons.
The cross-cutting safety net spanning Part A and Part B."""
import types, unittest
import _bootstrap  # noqa: F401
import agent_loop
from agent_loop import StepOutcome, BaseHandler


class _Func:
    def __init__(self, name, arguments): self.name, self.arguments = name, arguments

class _ToolCall:
    def __init__(self, name, arguments="{}", id="tid"): self.function, self.id = _Func(name, arguments), id

class _Resp:
    def __init__(self, content="", tool_calls=None): self.content, self.tool_calls = content, tool_calls or []

class ScriptedClient:
    def __init__(self, responses): self.responses, self.i, self.last_tools = responses, 0, ""
    def chat(self, messages, tools):
        resp = self.responses[self.i]; self.i += 1
        yield resp.content
        return resp

class Handler(BaseHandler):
    def __init__(self):
        self.parent = types.SimpleNamespace(task_dir=None)
        self._done_hooks = []
    def do_step(self, args, response):
        yield ""
        return StepOutcome({"n": 1}, next_prompt="continue")
    def do_done(self, args, response):
        yield ""
        return StepOutcome("final", next_prompt=None)         # -> CURRENT_TASK_DONE
    def do_stop(self, args, response):
        yield ""
        return StepOutcome("bye", should_exit=True)            # -> EXITED
    def do_no_tool(self, args, response):
        yield ""
        return StepOutcome(None, next_prompt=None)             # exercise no_tool routing


def run(responses, **kw):
    client = ScriptedClient(responses)
    g = agent_loop.agent_runner_loop(client, "sys", "hi", Handler(), [], verbose=False, **kw)
    return agent_loop.exhaust(g), client


class TestLoopProtocol(unittest.TestCase):
    def test_tool_chain_then_done(self):
        result, client = run([_Resp(tool_calls=[_ToolCall("step")]),
                              _Resp(tool_calls=[_ToolCall("done")])])
        self.assertEqual(result["result"], "CURRENT_TASK_DONE")
        self.assertEqual(client.i, 2)  # both turns consumed

    def test_should_exit(self):
        result, _ = run([_Resp(tool_calls=[_ToolCall("stop")])])
        self.assertEqual(result["result"], "EXITED")

    def test_no_tool_routing(self):
        result, _ = run([_Resp(content="plain text reply", tool_calls=[])])
        self.assertEqual(result["result"], "CURRENT_TASK_DONE")

    def test_max_turns_exceeded(self):
        result, _ = run([_Resp(tool_calls=[_ToolCall("step")]),
                         _Resp(tool_calls=[_ToolCall("step")])], max_turns=2)
        self.assertEqual(result["result"], "MAX_TURNS_EXCEEDED")


if __name__ == "__main__":
    unittest.main()
