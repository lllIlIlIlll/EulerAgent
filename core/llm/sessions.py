"""Sessions layer: per-backend session objects + request construction.

BaseSession + Claude/LLM/Native sessions. Builds provider payloads and drives the
wire transport, decoding via codec. Depends on config/wire/history/models/codec.
"""
import json, re, threading, uuid
from .config import safeprint
from .wire import auto_make_url, _stream_with_retry
from .history import trim_messages_history
from .models import model_caps
from .codec import *
print = safeprint

_RESP_CACHE_KEY = str(uuid.uuid4())


def _openai_stream(sess, messages):
    model, api_mode = sess.model, sess.api_mode
    caps = model_caps(model)
    temperature = sess.temperature
    if caps['temperature_override'] is not None: temperature = caps['temperature_override']
    elif caps['temperature_clamp']: lo, hi = caps['temperature_clamp']; temperature = max(lo, min(temperature, hi))
    headers = {"Authorization": f"Bearer {sess.api_key}", "Content-Type": "application/json", "Accept": "text/event-stream"}
    if api_mode == "responses":
        url = auto_make_url(sess.api_base, "responses")
        payload = {"model": model, "input": _to_responses_input(messages), "stream": sess.stream, 
                   "prompt_cache_key": _RESP_CACHE_KEY, "instructions": sess.system or "You are an Omnipotent Executor."}
        if sess.reasoning_effort: payload["reasoning"] = {"effort": sess.reasoning_effort}
        if sess.max_tokens: payload["max_output_tokens"] = sess.max_tokens
    else:
        url = auto_make_url(sess.api_base, "chat/completions")
        if sess.system: messages = [{"role": "system", "content": sess.system}] + messages
        _stamp_oai_cache_markers(messages, model)
        payload = {"model": model, "messages": messages, "stream": sess.stream}
        if sess.stream: payload["stream_options"] = {"include_usage": True}
        if temperature != 1: payload["temperature"] = temperature
        if sess.max_tokens: payload[caps['max_tokens_field']] = sess.max_tokens
        if sess.reasoning_effort: payload["reasoning_effort"] = sess.reasoning_effort
    tools = getattr(sess, 'tools', None)
    if tools: payload["tools"] = _prepare_oai_tools(tools, api_mode)
    if sess.service_tier: payload["service_tier"] = sess.service_tier
    parse_fn = (lambda r: _parse_openai_sse(r.iter_lines(), api_mode)) if sess.stream else (lambda r: _parse_openai_json(r.json(), api_mode))
    return (yield from _stream_with_retry(sess, url, headers, payload, parse_fn))

class BaseSession:
    def __init__(self, cfg):
        self.api_key = cfg['apikey']
        self.api_base = cfg['apibase'].rstrip('/')
        self.model = cfg.get('model', '')
        caps = model_caps(self.model)
        self.cut_msg_interval = caps['cut_msg_interval']; self.trim_keep_rate = caps['trim_keep_rate']
        self.keep_thinking = caps['keep_thinking']
        self.context_win = cfg.get('context_win', caps['context_win'])
        self.history = []; self.lock = threading.Lock(); self.system = ""
        self.name = cfg.get('name', self.model)
        proxy = cfg.get('proxy'); 
        self.proxies = {"http": proxy, "https": proxy} if proxy else None
        self.max_retries = max(0, int(cfg.get('max_retries', 4)))
        self.verify = cfg.get('verify', True)
        self.stream = cfg.get('stream', True)
        default_ct, default_rt = (5, 30) if self.stream else (10, 240)
        self.connect_timeout = max(1, int(cfg.get('timeout', default_ct)))
        self.read_timeout = max(5, int(cfg.get('read_timeout', default_rt)))
        def _enum(key, valid):
            v = cfg.get(key); v = None if v is None else str(v).strip().lower()
            return v if not v or v in valid else print(f"[WARN] Invalid {key} {v!r}, ignored.")
        self.reasoning_effort = _enum('reasoning_effort', {'none', 'minimal', 'low', 'medium', 'high', 'xhigh'})
        self.service_tier = _enum('service_tier', {'auto', 'default', 'priority', 'flex'})
        self.thinking_type = _enum('thinking_type', {'adaptive', 'enabled', 'disabled'})
        self.thinking_budget_tokens = cfg.get('thinking_budget_tokens')
        mode = str(cfg.get('api_mode', 'chat_completions')).strip().lower().replace('-', '_')
        self.api_mode = 'responses' if mode in ('responses', 'response') else 'chat_completions'
        self.temperature = cfg.get('temperature', 1)
        self.max_tokens = cfg.get('max_tokens')
    def _apply_claude_thinking(self, payload):
        if self.thinking_type:
            thinking = {"type": self.thinking_type}
            if self.thinking_type == 'enabled':
                if self.thinking_budget_tokens is None: print("[WARN] thinking_type='enabled' requires thinking_budget_tokens, ignored.")
                else:
                    thinking["budget_tokens"] = self.thinking_budget_tokens; payload["thinking"] = thinking
            else: payload["thinking"] = thinking
        if self.reasoning_effort:
            effort = {'low': 'low', 'medium': 'medium', 'high': 'high', 'xhigh': 'max'}.get(self.reasoning_effort)
            if effort: payload["output_config"] = {"effort": effort}
            else: print(f"[WARN] reasoning_effort {self.reasoning_effort!r} is unsupported for Claude output_config.effort, ignored.")
    def ask(self, prompt):
        def _ask_gen():
            with self.lock:
                self.history.append({"role": "user", "content": [{"type": "text", "text": prompt}]})
                trim_messages_history(self.history, self)
                messages = self.make_messages(self.history)
            content_blocks = None; content = ''
            gen = self.raw_ask(messages)
            try:
                while True: chunk = next(gen); content += chunk; yield chunk
            except StopIteration as e: content_blocks = e.value or []
            for block in (content_blocks or []):
                if block.get('type', '') == 'tool_use':
                    tu = {'name': block.get('name', ''), 'arguments': block.get('input', {})}
                    yield f'<tool_use>{json.dumps(tu, ensure_ascii=False)}</tool_use>'
            if content.strip() and not content.startswith("!!!Error:"): self.history.append({"role": "assistant", "content": [{"type": "text", "text": content}]})
        return _ask_gen() if self.stream else ''.join(list(_ask_gen()))

class ClaudeSession(BaseSession):
    def raw_ask(self, messages):
        messages = _fix_messages(messages)
        if self.max_tokens is None: self.max_tokens = 8192
        headers = {"x-api-key": self.api_key, "Content-Type": "application/json", "anthropic-version": "2023-06-01", "anthropic-beta": "prompt-caching-2024-07-31"}
        payload = {"model": self.model, "messages": messages, "max_tokens": self.max_tokens, "stream": self.stream}
        if self.temperature != 1: payload["temperature"] = self.temperature
        self._apply_claude_thinking(payload)
        if self.system: payload["system"] = [{"type": "text", "text": self.system, "cache_control": {"type": "persistent"}}]
        url = auto_make_url(self.api_base, "messages")
        parse_fn = (lambda r: _parse_claude_sse(r.iter_lines())) if self.stream else (lambda r: _parse_claude_json(r.json()))
        return (yield from _stream_with_retry(self, url, headers, payload, parse_fn))
    def make_messages(self, raw_list):
        msgs = _drop_unsigned_thinking([{"role": m['role'], "content": list(m['content'])} for m in raw_list])
        user_idxs = [i for i, m in enumerate(msgs) if m['role'] == 'user']
        for idx in user_idxs[-2:]:
            msgs[idx]["content"][-1] = dict(msgs[idx]["content"][-1], cache_control={"type": "ephemeral"})
        return msgs

class LLMSession(BaseSession):
    def raw_ask(self, messages): return (yield from _openai_stream(self, messages))
    def make_messages(self, raw_list): return _msgs_claude2oai(_fix_messages(raw_list))

class NativeClaudeSession(BaseSession):
    def __init__(self, cfg):
        super().__init__(cfg)
        self.fake_cc_system_prompt = cfg.get("fake_cc_system_prompt", False)
        self.user_agent = cfg.get("user_agent", "claude-cli/2.1.113 (external, cli)")
        self._session_id = str(uuid.uuid4())
        self._account_uuid = str(uuid.uuid4())
        self._device_id = uuid.uuid4().hex + uuid.uuid4().hex[:32]
        self.tools = None
    def raw_ask(self, messages):
        if self.max_tokens is None: self.max_tokens = 8192
        model = self.model
        messages = _fix_messages(messages)
        if 'claude' in model.lower(): messages = _drop_unsigned_thinking(messages)
        messages = _ensure_thinking_blocks(messages, self.model)
        beta_parts = ["claude-code-20250219", "interleaved-thinking-2025-05-14", "redact-thinking-2026-02-12", "prompt-caching-scope-2026-01-05"]
        if "[1m]" in model.lower():
            beta_parts.insert(1, "context-1m-2025-08-07"); model = model.replace("[1m]", "").replace("[1M]", "")
        headers = {"Content-Type": "application/json", "anthropic-version": "2023-06-01",
            "anthropic-beta": ",".join(beta_parts), "anthropic-dangerous-direct-browser-access": "true",
            "user-agent": self.user_agent, "x-app": "cli"}
        if self.api_key.startswith("sk-ant-"): headers["x-api-key"] = self.api_key
        else: headers["authorization"] = f"Bearer {self.api_key}"
        payload = {"model": model, "messages": messages, "max_tokens": self.max_tokens, "stream": self.stream}
        if self.temperature != 1: payload["temperature"] = self.temperature
        self._apply_claude_thinking(payload)
        payload["metadata"] = {"user_id": json.dumps({"device_id": self._device_id, "account_uuid": self._account_uuid, "session_id": self._session_id}, separators=(',', ':'))}
        if self.tools:
            claude_tools = openai_tools_to_claude(self.tools)
            tools = [dict(t) for t in claude_tools]; tools[-1]["cache_control"] = {"type": "ephemeral"}
            payload["tools"] = tools
        else: print("[ERROR] No tools provided for this session.")
        payload['system'] = [{"type": "text", "text": "You are Claude Code, Anthropic's official CLI for Claude.", "cache_control": {"type": "ephemeral"}}]
        if self.system:
            if self.fake_cc_system_prompt: messages[0]["content"].insert(0, {"type": "text", "text": self.system})
            else: payload["system"] = [{"type": "text", "text": self.system}]
        user_idxs = [i for i, m in enumerate(messages) if m['role'] == 'user']
        for idx in user_idxs[-2:]:
            messages[idx] = {**messages[idx], "content": list(messages[idx]["content"])}
            messages[idx]["content"][-1] = dict(messages[idx]["content"][-1], cache_control={"type": "ephemeral"})
        url = auto_make_url(self.api_base, "messages") + '?beta=true'
        parse_fn = (lambda r: _parse_claude_sse(r.iter_lines())) if self.stream else (lambda r: _parse_claude_json(r.json()))
        return (yield from _stream_with_retry(self, url, headers, payload, parse_fn))

    def ask(self, msg):
        assert type(msg) is dict
        with self.lock:
            self.history.append(msg)
            trim_messages_history(self.history, self)
            messages = [{"role": m["role"], "content": list(m["content"])} for m in self.history]
        content_blocks = None
        gen = self.raw_ask(messages)
        try:
            while True: yield next(gen)
        except StopIteration as e: content_blocks = e.value or []
        if content_blocks and (_injected := _ensure_text_block(content_blocks)): yield _injected
        if content_blocks and not (len(content_blocks) == 1 and content_blocks[0].get("text", "").startswith("!!!Error:")):
            self.history.append({"role": "assistant", "content": content_blocks})
        text_parts = [b["text"] for b in content_blocks if b.get("type") == "text"]
        content = "\n".join(text_parts).strip()
        tool_calls = [MockToolCall(b["name"], b.get("input", {}), id=b.get("id", "")) for b in content_blocks if b.get("type") == "tool_use"]
        if not tool_calls: tool_calls, content = _parse_text_tool_calls(content)
        thinking_parts = [b["thinking"] for b in content_blocks if b.get("type") == "thinking"]
        thinking = "\n".join(thinking_parts).strip()
        if not thinking:
            think_pattern = r"<think(?:ing)?>(.*?)</think(?:ing)?>"
            think_match = re.search(think_pattern, content, re.DOTALL)
            if think_match:
                thinking = think_match.group(1).strip()
                content = re.sub(think_pattern, "", content, flags=re.DOTALL)
        return MockResponse(thinking, content, tool_calls, str(content_blocks))

class NativeOAISession(NativeClaudeSession):
    def raw_ask(self, messages):
        messages = _fix_messages(messages)
        messages = _ensure_thinking_blocks(messages, self.model)
        return (yield from _openai_stream(self, _msgs_claude2oai(messages)))
