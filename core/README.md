# core/

Application runtime. `core/agentmain.py` is the entry point; everything else is
one of: the Agent Loop, the tool implementations, the LLM adapter, or a
compatibility shim.

> Architecture, path rules, and PR constraints live in the root [CLAUDE.md](../CLAUDE.md)
> and [CONTRIBUTING.md](../CONTRIBUTING.md). This file is a module index, not a style guide.

## Module map

| File | Lines | Role |
|---|---:|---|
| `agentmain.py` | 299 | `EulerAgent` class — the application entry point. Builds the system prompt, wires the LLM client, and kicks off the loop. |
| `agent_loop.py` | 136 | `agent_runner_loop` — the perceive → reason → act → record loop. The single hot path. |
| `ea.py` | 619 | `EulerAgentHandler` — implementation of the 9 atomic tools (`code_run`, `file_read/write/patch`, `web_scan`, `web_execute_js`, `ask_user`, plus the two memory hooks). |
| `llmcore.py` | 11 | **Compat shim** — `from llmcore import ...` keeps working. Forwards to `llm/` package via `__getattr__`. New code should import from `llm` directly. |

## `llm/` — LLM adapter package

Layered, single-direction dependencies. The public facade is `llm/__init__.py`.

| File | Role |
|---|---|
| `config.py` | `ekey.json` loading + `safeprint` |
| `models.py` | Model capability table (D4) |
| `history.py` | Context compress / trim |
| `wire.py` | HTTP/SSE transport + retry |
| `codec.py` | Protocol encode/decode + `Mock*` + parsing |
| `sessions.py` | `BaseSession` + backend sessions |
| `clients.py` | Tool clients + `resolve_*` |

Layering (lower cannot import higher):
```
config → models → codec → history → wire → sessions → clients
```

## `handlers/`

Reserved for the `BaseHandler` extension pattern. Currently empty; concrete
handlers live inside `ea.py` until the pattern stabilises.

## Path rules (do not break)

`memory/`, `assets/`, `temp/` sit at the **project root**, not inside `core/`.
Every reference from a `core/` module uses a parent-relative path:

```python
script_dir = os.path.dirname(os.path.abspath(__file__))
os.path.join(script_dir, '../memory/...')   # not 'memory/...'
os.path.join(script_dir, '../assets/...')
os.path.join(script_dir, '../temp/...')
```

## Import convention

`agentmain.py` inserts `core/` itself at the front of `sys.path`, so sibling
modules import by **bare name** — there is no `core.` package prefix anywhere
in the repo:

```python
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from llmcore import reload_ekeys, LLMSession
from agent_loop import agent_runner_loop
from ea import EulerAgentHandler
```
