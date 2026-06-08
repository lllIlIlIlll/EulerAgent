"""LLM adapter package.

Strangler split in progress: the implementation still lives in `_legacy.py` and is
re-exported here. Public symbols come through `from ._legacy import *`; a few private
helpers are re-exported explicitly, and `__getattr__` delegates lazy module attributes
(e.g. `ekeys`) to _legacy. An explicit `__all__` lands in the final stage, once symbols
are spread across config/codec/wire/sessions/clients modules.
"""
from ._legacy import *  # noqa: F401,F403
from ._legacy import (  # private helpers referenced cross-module / by the test net
    _msgs_claude2oai, _to_responses_input, _fix_messages,
    _parse_claude_sse, _parse_openai_sse, _parse_text_tool_calls, _ensure_thinking_blocks,
)

def __getattr__(name):
    from . import _legacy
    return getattr(_legacy, name)
