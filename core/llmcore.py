"""Compatibility shim — `from llmcore import ...` keeps working unchanged.

The implementation lives in the `llm` package (core/llm/). `core/` is injected as a
top-level path (see core/agentmain.py), so both `llmcore` and `llm` resolve from there.
`__getattr__` delegates private symbols and lazy attributes (e.g. `ekeys`) to the package.
"""
import llm as _pkg
from llm import *  # noqa: F401,F403

def __getattr__(name):
    return getattr(_pkg, name)
