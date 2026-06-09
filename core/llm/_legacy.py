import os, json, re, time, requests, sys, threading, urllib3, base64, importlib, uuid
from datetime import datetime
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
_RESP_CACHE_KEY = str(uuid.uuid4())
from .config import _CORE_DIR, safeprint, reload_ekeys  # config leaf module
from .wire import auto_make_url, _record_usage, _stream_with_retry, _write_llm_log  # wire leaf module
from .codec import (_parse_claude_json, _parse_claude_sse, _try_parse_tool_args, _parse_openai_sse,
                    _parse_openai_json, _stamp_oai_cache_markers, _prepare_oai_tools, _to_responses_input,
                    _msgs_claude2oai, _keep_claude_block, _drop_unsigned_thinking, _ensure_thinking_blocks,
                    _fix_messages, openai_tools_to_claude, tryparse)  # codec leaf module
from .codec import MockFunction, MockToolCall, MockResponse, _ensure_text_block, _parse_text_tool_calls  # codec primitives
print = safeprint

def __getattr__(name):  # PEP 562: lazy 'ekeys' + delegate config-only names
    if name == 'ekeys': return reload_ekeys()[0]
    from . import config
    return getattr(config, name)

from .history import compress_history_tags, _sanitize_leading_user_msg, trim_messages_history  # history leaf module


from .models import model_caps  # D4 capability table (extracted leaf module)


    


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
            if len(content_blocks) > 1: print(f"[DEBUG BaseSession.ask] content_blocks: {content_blocks}")
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


  
         


class ToolClient:
    def __init__(self, backend, auto_save_tokens=True):
        self.backend = backend
        self.auto_save_tokens = auto_save_tokens
        self.last_tools = ''
        self.name = self.backend.name
        self.total_cd_tokens = 0
        self.log_path = None

    def chat(self, messages, tools=None):
        tools = json.loads(json.dumps(tools, ensure_ascii=False)) if tools else tools
        for t in tools or []:
            f = t.get('function', {})
            if f.get('name') == 'file_write':
                props = f.get('parameters', {}).get('properties', {})
                props.pop('content', None)
                extra = '. Content must be placed in <file_content> tags in reply body, not in args'
                if extra not in f.get('description', ''): f['description'] = f.get('description', '') + extra
                break
        full_prompt = self._build_protocol_prompt(messages, tools)
        print("Full prompt length:", len(full_prompt), 'chars')
        gen = self.backend.ask(full_prompt)
        _write_llm_log('Prompt', full_prompt, self.log_path)
        raw_text = ''
        for chunk in gen:
            raw_text += chunk; yield chunk
        _write_llm_log('Response', raw_text, self.log_path)
        return self._parse_mixed_response(raw_text)

    def _prepare_tool_instruction(self, tools):
        tool_instruction = ""
        if not tools: return tool_instruction
        tools_json = json.dumps(tools, ensure_ascii=False, separators=(',', ':'))
        _en = os.environ.get('GA_LANG') == 'en'
        if _en:
            tool_instruction = f"""
### Interaction Protocol (must follow strictly, always in effect)
Follow these steps to think and act:
1. **Think**: Analyze the current situation and strategy inside `<thinking>` tags.
2. **Summarize**: Output a minimal one-line (<30 words) physical snapshot in `<summary>`: new info from last tool result + current tool call intent. This goes into long-term working memory. Must contain real information, no filler.
3. **Act**: If you need to call tools, output one or more **<tool_use> blocks** after your reply, then stop.
"""
        else:
            tool_instruction = f"""
### 交互协议 (必须严格遵守，持续有效)
请按照以下步骤思考并行动：
1. **思考**: 在 `<thinking>` 标签中先进行思考，分析现状和策略。
2. **总结**: 在 `<summary>` 中输出*极为简短*的高度概括的单行（<30字）物理快照，包括上次工具调用结果产生的新信息+本次工具调用意图。此内容将进入长期工作记忆，记录关键信息，严禁输出无实际信息增量的描述。
3. **行动**: 如需调用工具，请在回复正文之后输出一个（或多个）**<tool_use>块**，然后结束。
"""
        tool_instruction += f'\nFormat: ```<tool_use>{{"name": "tool_name", "arguments": {{...}}}}</tool_use>```\n\n### Tools (mounted, always in effect):\n{tools_json}\n'
        if self.auto_save_tokens and self.last_tools == tools_json:
            tool_instruction = "\n### Tools: still active, **ready to call**. Protocol unchanged.\n" if _en else "\n### 工具库状态：持续有效（code_run/file_read等），**可正常调用**。调用协议沿用。\n"
        else: self.total_cd_tokens = 0
        self.last_tools = tools_json
        return tool_instruction

    def _build_protocol_prompt(self, messages, tools):
        system_content = next((m['content'] for m in messages if m['role'].lower() == 'system'), "")
        history_msgs = [m for m in messages if m['role'].lower() != 'system']
        tool_instruction = self._prepare_tool_instruction(tools)
        system = ""; user = ""
        if system_content: system += f"{system_content}\n"
        system += f"{tool_instruction}"
        for m in history_msgs:
            role = "USER" if m['role'] == 'user' else "ASSISTANT"
            user += f"=== {role} ===\n"
            for tr in m.get('tool_results', []): user += f'<tool_result>{tr["content"]}</tool_result>\n'
            user += str(m['content']) + "\n"
            self.total_cd_tokens += len(user) // 3
        if self.total_cd_tokens > 9000: self.last_tools = ''
        user += "=== ASSISTANT ===\n" 
        return system + user

    def _parse_mixed_response(self, text):
        remaining_text = text; thinking = ''
        think_match = re.search(r"<think(?:ing)?>(.*?)</think(?:ing)?>", text, re.DOTALL)
        if think_match:
            thinking = think_match.group(1).strip()
            remaining_text = re.sub(r"<think(?:ing)?>(.*?)</think(?:ing)?>", "", remaining_text, flags=re.DOTALL)
        tool_calls, remaining_text = _parse_text_tool_calls(remaining_text)
        if not tool_calls:
            json_strs = []; errors = []
            if '<tool_use>' in remaining_text:
                weaktoolstr = remaining_text.split('<tool_use>')[-1].strip().strip('><')
                json_str = weaktoolstr if weaktoolstr.endswith('}') else ''
                if json_str == '' and '```' in weaktoolstr and weaktoolstr.split('```')[0].strip().endswith('}'):
                    json_str = weaktoolstr.split('```')[0].strip()
                if json_str: json_strs.append(json_str)
                remaining_text = remaining_text.replace('<tool_use>'+weaktoolstr, "")
            elif '"name":' in remaining_text and '"arguments":' in remaining_text:
                json_match = re.search(r'\{.*"name":.*\}', remaining_text, re.DOTALL)
                if json_match:
                    json_strs.append(json_match.group(0).strip())
                    remaining_text = remaining_text.replace(json_match.group(0), "").strip()
            for json_str in json_strs:
                try:
                    data = tryparse(json_str)
                    func_name = data.get('name') or data.get('function') or data.get('tool')
                    args = data.get('arguments') or data.get('args') or data.get('params') or data.get('parameters')
                    if args is None: args = data
                    if func_name: tool_calls.append(MockToolCall(func_name, args))
                except json.JSONDecodeError:
                    errors.append(f'Failed to parse tool_use JSON: {json_str[:200]}')
                    self.last_tools = ''
            if not tool_calls:
                for e in errors:
                    print(f"[Warn] {e}"); tool_calls.append(MockToolCall('bad_json', {'msg': e}))
        return MockResponse(thinking, remaining_text.strip(), tool_calls, text)


class MixinSession:
    """Multi-session fallback with spring-back to primary."""
    def __init__(self, all_sessions, cfg):
        self._retries, self._base_delay = cfg.get('max_retries', 3), cfg.get('base_delay', 1.5)
        self._spring_sec = cfg.get('spring_back', 300)
        self._sessions = [all_sessions[i].backend if isinstance(i, int) else 
                          next(s.backend for s in all_sessions if type(s) is not dict and s.backend.name == i) for i in cfg.get('llm_nos', [])]
        is_native = lambda s: 'Native' in s.__class__.__name__
        groups = {is_native(s) for s in self._sessions}
        assert len(groups) == 1, f"MixinSession: sessions must be in same group (Native or non-Native), got {[type(s).__name__ for s in self._sessions]}"
        self.name = '|'.join(s.name for s in self._sessions)
        import copy; self._sessions = [copy.copy(s) for s in self._sessions]
        for s in self._sessions: s.max_retries = 0
        self._orig_raw_asks = [s.raw_ask for s in self._sessions]
        self._sessions[0].raw_ask = self._raw_ask
        self._cur_idx, self._switched_at = 0, 0.0
    def __getattr__(self, name): return getattr(self._sessions[0], name)
    _BROADCAST_ATTRS = frozenset({'system', 'tools', 'temperature', 'max_tokens', 'reasoning_effort', 'history'})
    def __setattr__(self, name, value):
        if name in self._BROADCAST_ATTRS:
            for s in self._sessions:
                v = openai_tools_to_claude(value) if name == 'tools' and type(s) is NativeClaudeSession else value
                setattr(s, name, v)
        else: object.__setattr__(self, name, value)
    @property
    def primary(self): return self._sessions[0]
    @property
    def model(self): return getattr(self._sessions[self._cur_idx], 'model', None)
    def _pick(self):
        if self._cur_idx and time.time() - self._switched_at > self._spring_sec: self._cur_idx = 0
        return self._cur_idx
    def _raw_ask(self, *args, **kwargs):
        base, n = self._pick(), len(self._sessions)
        test_error = lambda x: isinstance(x, str) and x.lstrip().startswith(('!!!Error:', '[Error:'))
        for attempt in range(self._retries + 1):
            idx = (base + attempt) % n
            gen = self._orig_raw_asks[idx](*args, **kwargs)
            print(f'[MixinSession] Using session ({self._sessions[idx].name})')
            last_chunk, return_val, yielded = None, [], False
            try:
                while True:
                    chunk = next(gen); last_chunk = chunk
                    if not yielded and test_error(chunk): continue
                    yield chunk; yielded = True
            except StopIteration as e: return_val = e.value or []
            is_err = test_error(last_chunk)
            if not is_err:
                if attempt > 0: self._cur_idx = idx; self._switched_at = time.time()
                elif isinstance(last_chunk, str) and '[!!! 流异常中断' in last_chunk and n > 1:
                    self._cur_idx = (idx + 1) % n; self._switched_at = time.time()
                    print(f'[MixinSession] Partial failure, next call → s{self._cur_idx} ({self._sessions[self._cur_idx].name})')
                return return_val
            if attempt >= self._retries:
                yield last_chunk; return return_val
            nxt = (base + attempt + 1) % n
            if nxt == base:  # full round failed, delay before next
                rnd = (attempt + 1) // n
                delay = min(30, self._base_delay * (1.5 ** rnd))
                print(f'[MixinSession] {last_chunk[:80]}, round {rnd} exhausted, retry in {delay:.1f}s')
                time.sleep(delay)
            else: print(f'[MixinSession] {last_chunk[:80]}, retry {attempt+1}/{self._retries} (s{idx}→s{nxt})')

THINKING_PROMPT_ZH = """
### 行动规范（持续有效）
每次回复（含工具调用轮）都先在回复文字中包含一个<summary></summary> 中输出极简单行（<30字）物理快照：上次结果新信息+本次意图。此内容进入长期工作记忆。
\n**若用户需求未完成，必须进行工具调用！**
""".strip()
THINKING_PROMPT_EN = """
### Action Protocol (always in effect)
The reply body should first include a minimal one-line (<30 words) physical snapshot in <summary></summary>: new info from last result + current intent. This goes into long-term working memory.
\n**If the user's request is not yet complete, tool calls are required!**
""".strip()

class NativeToolClient:
    @staticmethod
    def _thinking_prompt(): return THINKING_PROMPT_EN if os.environ.get('GA_LANG') == 'en' else THINKING_PROMPT_ZH
    def __init__(self, backend):
        self.backend = backend
        self.backend.system = self._thinking_prompt()
        self.name = self.backend.name
        self._pending_tool_ids = []
        self.log_path = None
    def set_system(self, extra_system):
        combined = f"{extra_system}\n\n{self._thinking_prompt()}" if extra_system else self._thinking_prompt()
        if combined != self.backend.system: print(f"[Debug] Updated system prompt, length {len(combined)} chars.")
        self.backend.system = combined
    def chat(self, messages, tools=None):
        if tools: self.backend.tools = tools
        if not self.backend.history: self._pending_tool_ids = []
        combined_content = []; resp = None; tool_results = []
        for msg in messages:
            c = msg.get('content', '')
            if msg['role'] == 'system': 
                self.set_system(c); continue
            if isinstance(c, str): combined_content.append({"type": "text", "text": c})
            elif isinstance(c, list): combined_content.extend(c)
            if msg['role'] == 'user' and msg.get('tool_results'): tool_results.extend(msg['tool_results'])
        tr_id_set = set();  tool_result_blocks = []
        for tr in tool_results:
            tool_use_id, content = tr.get("tool_use_id", ""), tr.get("content", "")
            tr_id_set.add(tool_use_id)
            if tool_use_id: tool_result_blocks.append({"type": "tool_result", "tool_use_id": tool_use_id, "content": tr.get("content", "")})
            else: combined_content = [{"type": "text", "text": f'<tool_result>{content}</tool_result>'}] + combined_content
        for tid in self._pending_tool_ids:
            if tid not in tr_id_set: tool_result_blocks.append({"type": "tool_result", "tool_use_id": tid, "content": ""})
        self._pending_tool_ids = []
        # Filter whitespace-only text blocks that cause 400 on strict API proxies
        filtered_content = [c for c in combined_content if c.get("text", "").strip()]
        final_content = tool_result_blocks + filtered_content
        if not final_content: final_content = [{"type": "text", "text": "."}]
        merged = {"role": "user", "content": final_content}
        _write_llm_log('Prompt', json.dumps(merged, ensure_ascii=False, indent=2), self.log_path)
        gen = self.backend.ask(merged)
        try:
            while True: 
                chunk = next(gen); yield chunk
        except StopIteration as e: resp = e.value
        if resp: _write_llm_log('Response', resp.raw, self.log_path)
        if resp and hasattr(resp, 'tool_calls') and resp.tool_calls: self._pending_tool_ids = [tc.id for tc in resp.tool_calls]
        return resp

def resolve_session(cfg_name):
    cfg = reload_ekeys()[0].get(cfg_name)
    if not cfg: raise ValueError(f"Config '{cfg_name}' not in ekey")
    if 'native' in cfg_name: return (NativeClaudeSession if 'claude' in cfg_name else NativeOAISession)(cfg=cfg)
    if 'claude' in cfg_name: return ClaudeSession(cfg=cfg)
    return LLMSession(cfg=cfg) if 'oai' in cfg_name else None

def resolve_client(cfg_name):
    s = resolve_session(cfg_name)
    return (NativeToolClient(s) if isinstance(s, (NativeClaudeSession, NativeOAISession)) else ToolClient(s)) if s else None

def fast_ask(prompt, cfg_name):
    sess = resolve_session(cfg_name)
    if not sess: raise ValueError(f"fast_ask: '{cfg_name}' unsupported")
    return "".join(sess.raw_ask([{"role": "user", "content": prompt}]))
