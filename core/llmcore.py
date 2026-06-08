"""Compatibility shim — `from llmcore import ...` keeps working unchanged.

The implementation moved to the `llm` package (core/llm/). `core/` is injected as a
top-level path (see core/agentmain.py), so both `llmcore` and `llm` resolve from there.
`__getattr__` delegates private symbols and lazy attributes (e.g. `ekeys`) to _legacy.
"""
from llm import *  # noqa: F401,F403
from llm import _legacy as _impl

def __getattr__(name):
    return getattr(_impl, name)
