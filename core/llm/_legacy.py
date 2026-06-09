import os, json, re, time, requests, sys, threading, urllib3, base64, importlib, uuid
from datetime import datetime
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
from .config import _CORE_DIR, safeprint, reload_ekeys  # config leaf module
from .wire import auto_make_url, _record_usage, _stream_with_retry, _write_llm_log  # wire leaf module
from .codec import (_parse_claude_json, _parse_claude_sse, _try_parse_tool_args, _parse_openai_sse,
                    _parse_openai_json, _stamp_oai_cache_markers, _prepare_oai_tools, _to_responses_input,
                    _msgs_claude2oai, _keep_claude_block, _drop_unsigned_thinking, _ensure_thinking_blocks,
                    _fix_messages, openai_tools_to_claude, tryparse)  # codec leaf module
from .codec import MockFunction, MockToolCall, MockResponse, _ensure_text_block, _parse_text_tool_calls  # codec primitives
from .sessions import _openai_stream, BaseSession, ClaudeSession, LLMSession, NativeClaudeSession, NativeOAISession  # sessions module
from .clients import ToolClient, MixinSession, NativeToolClient, resolve_session, resolve_client, fast_ask  # clients module
print = safeprint

def __getattr__(name):  # PEP 562: lazy 'ekeys' + delegate config-only names
    if name == 'ekeys': return reload_ekeys()[0]
    from . import config
    return getattr(config, name)

from .history import compress_history_tags, _sanitize_leading_user_msg, trim_messages_history  # history leaf module


from .models import model_caps  # D4 capability table (extracted leaf module)


    


        


  
         


