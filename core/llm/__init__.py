"""LLM adapter package — public API aggregated from the layer modules.

Dependency order (acyclic): config / models / history → wire → codec → sessions → clients.
`__getattr__` serves the lazy, mtime-guarded `ekeys` and any other config-owned name.
"""
from .config import reload_ekeys, safeprint
from .models import model_caps
from .history import compress_history_tags, _sanitize_leading_user_msg, trim_messages_history
from .wire import auto_make_url, _record_usage, _stream_with_retry, _write_llm_log
from .codec import *  # protocol codecs + Mock* + text tool parsing (codec defines __all__)
from .sessions import BaseSession, ClaudeSession, LLMSession, NativeClaudeSession, NativeOAISession, _openai_stream
from .clients import ToolClient, MixinSession, NativeToolClient, resolve_session, resolve_client, fast_ask

def __getattr__(name):
    if name == 'ekeys': return reload_ekeys()[0]
    from . import config
    return getattr(config, name)
