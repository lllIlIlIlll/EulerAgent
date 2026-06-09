"""Codec layer: protocol encode/decode between Claude and OpenAI (chat + responses)
formats, SSE/JSON stream parsing, message repair, and tool-schema conversion.

Imports: config (safeprint), wire (_record_usage), models (model_caps).
"""
import json, re, uuid
from .config import safeprint
from .wire import _record_usage
from .models import model_caps
print = safeprint


def _parse_claude_json(data):
    content_blocks = data.get("content", [])
    _record_usage(data.get("usage", {}), "messages")
    for b in content_blocks:
        if b.get("type") == "text": yield b.get("text", "")
        elif b.get("type") == "thinking": yield ""
    return content_blocks

def _parse_claude_sse(resp_lines):
    """Parse Anthropic SSE stream. Yields text chunks, returns list[content_block]."""
    content_blocks = []; current_block = None; tool_json_buf = ""
    stop_reason = None; got_message_stop = False; warn = None
    for line in resp_lines:
        if not line: continue
        line = line.decode('utf-8') if isinstance(line, bytes) else line
        if not line.startswith("data:"): continue
        data_str = line[5:].lstrip()
        if data_str == "[DONE]": break
        try: evt = json.loads(data_str)
        except json.JSONDecodeError as e:
            print(f"[SSE] JSON parse error: {e}, line: {data_str[:200]}")
            continue
        evt_type = evt.get("type", "")
        if evt_type == "message_start":
            usage = evt.get("message", {}).get("usage", {})
            _record_usage(usage, "messages")
        elif evt_type == "content_block_start":
            block = evt.get("content_block", {})
            if block.get("type") == "text": current_block = {"type": "text", "text": ""}
            elif block.get("type") == "thinking": current_block = {"type": "thinking", "thinking": "", "signature": ""}
            elif block.get("type") == "tool_use":
                current_block = {"type": "tool_use", "id": block.get("id", ""), "name": block.get("name", ""), "input": {}}
                tool_json_buf = ""
        elif evt_type == "content_block_delta":
            delta = evt.get("delta", {})
            if delta.get("type") == "text_delta":
                text = delta.get("text", "")
                if current_block and current_block.get("type") == "text": current_block["text"] += text
                if text: yield text
            elif delta.get("type") == "thinking_delta":
                if current_block and current_block.get("type") == "thinking": current_block["thinking"] += delta.get("thinking", "")
            elif delta.get("type") == "signature_delta":
                if current_block and current_block.get("type") == "thinking":
                    current_block["signature"] = current_block.get("signature", "") + delta.get("signature", "")
            elif delta.get("type") == "input_json_delta": tool_json_buf += delta.get("partial_json", "")
        elif evt_type == "content_block_stop":
            if current_block:
                if current_block["type"] == "tool_use":
                    try: current_block["input"] = json.loads(tool_json_buf) if tool_json_buf else {}
                    except json.JSONDecodeError: current_block["input"] = {"_raw": tool_json_buf}
                content_blocks.append(current_block)
                current_block = None
        elif evt_type == "message_delta":
            delta = evt.get("delta", {})
            stop_reason = delta.get("stop_reason", stop_reason)
            out_usage = evt.get("usage", {})
            out_tokens = out_usage.get("output_tokens", 0)
            if out_tokens: print(f"[Output] tokens={out_tokens} stop_reason={stop_reason}")
        elif evt_type == "message_stop": got_message_stop = True
        elif evt_type == "error":
            err = evt.get("error", {})
            emsg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
            warn = f"\n\n!!!Error: SSE {emsg}"; break
    if not warn:
        if not got_message_stop and not stop_reason: warn = "\n\n[!!! 流异常中断，未收到完整响应 !!!]"
        elif stop_reason == "max_tokens": warn = "\n\n[!!! Response truncated: max_tokens !!!]"
    if current_block:
        if current_block["type"] == "tool_use":
            try: current_block["input"] = json.loads(tool_json_buf) if tool_json_buf else {}
            except json.JSONDecodeError: current_block["input"] = {"_raw": tool_json_buf}
        content_blocks.append(current_block); current_block = None
    if warn:
        print(f"[WARN] {warn.strip()}")
        content_blocks.append({"type": "text", "text": warn}); yield warn
    return content_blocks

def _try_parse_tool_args(raw):
    """Parse tool args string; split concatenated JSON objects like {..}{..} if needed.
    Returns list of parsed dicts."""
    if not raw: return [{}]
    try: return [json.loads(raw)]
    except json.JSONDecodeError: pass
    parts = re.split(r'(?<=\})(?=\{)', raw)
    if len(parts) > 1:
        parsed = []
        for p in parts:
            try: parsed.append(json.loads(p))
            except json.JSONDecodeError: return [{"_raw": raw}]
        return parsed
    return [{"_raw": raw}]

def _parse_openai_sse(resp_lines, api_mode="chat_completions"):
    """Parse OpenAI SSE stream (chat_completions or responses API).
    Yields text chunks, returns list[content_block].
    content_block: {type:'text', text:str} | {type:'tool_use', id:str, name:str, input:dict}
    """
    content_text = ""
    if api_mode == "responses":
        seen_delta = False; fc_buf = {}; current_fc_idx = None
        for line in resp_lines:
            if not line: continue
            line = line.decode('utf-8', errors='replace') if isinstance(line, bytes) else line
            if not line.startswith("data:"): continue
            data_str = line[5:].lstrip()
            if data_str == "[DONE]": break
            try: evt = json.loads(data_str)
            except json.JSONDecodeError: continue
            etype = evt.get("type", "")
            if etype == "response.output_text.delta":
                delta = evt.get("delta", "")
                if delta: seen_delta = True; content_text += delta; yield delta
            elif etype == "response.output_text.done" and not seen_delta:
                text = evt.get("text", "")
                if text: content_text += text; yield text
            elif etype == "response.output_item.added":
                item = evt.get("item", {})
                if item.get("type") == "function_call":
                    idx = evt.get("output_index", 0)
                    fc_buf[idx] = {"id": item.get("call_id", item.get("id", "")), "name": item.get("name", ""), "args": ""}
                    current_fc_idx = idx
            elif etype == "response.function_call_arguments.delta":
                idx = evt.get("output_index", current_fc_idx or 0)
                if idx in fc_buf: fc_buf[idx]["args"] += evt.get("delta", "")
            elif etype == "response.function_call_arguments.done":
                idx = evt.get("output_index", current_fc_idx or 0)
                if idx in fc_buf: fc_buf[idx]["args"] = evt.get("arguments", fc_buf[idx]["args"])
            elif etype == "error":
                err = evt.get("error", {})
                emsg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
                if emsg: content_text += f"!!!Error: {emsg}"; yield f"!!!Error: {emsg}"
                break
            elif etype == "response.completed":
                usage = evt.get("response", {}).get("usage", {})
                _record_usage(usage, api_mode)
                break
        blocks = []
        if content_text: blocks.append({"type": "text", "text": content_text})
        for idx in sorted(fc_buf):
            fc = fc_buf[idx]
            inps = _try_parse_tool_args(fc["args"])
            for i, inp in enumerate(inps):
                bid = fc["id"] or ''
                if len(inps) > 1: bid = f"{bid}_{i}" if bid else f"split_{i}"
                blocks.append({"type": "tool_use", "id": bid, "name": fc["name"], "input": inp})
        return blocks
    else:
        tc_buf = {}  # index -> {id, name, args}
        reasoning_text = ""
        for line in resp_lines:
            if not line: continue
            line = line.decode('utf-8', errors='replace') if isinstance(line, bytes) else line
            if not line.startswith("data:"): continue
            data_str = line[5:].lstrip()
            if data_str == "[DONE]": break
            try: evt = json.loads(data_str)
            except json.JSONDecodeError: continue
            ch = (evt.get("choices") or [{}])[0]
            delta = ch.get("delta") or {}
            if delta.get("reasoning_content"):
                reasoning_text += delta["reasoning_content"]
            if delta.get("content"):
                text = delta["content"]; content_text += text; yield text
            for tc in (delta.get("tool_calls") or []):
                idx = tc.get("index", 0)
                has_name = bool(tc.get("function", {}).get("name"))
                if idx not in tc_buf:
                    if has_name or not tc_buf: tc_buf[idx] = {"id": tc.get("id") or '', "name": "", "args": ""}
                    else: idx = max(tc_buf)
                if has_name: tc_buf[idx]["name"] = tc["function"]["name"]
                if tc.get("function", {}).get("arguments"): tc_buf[idx]["args"] += tc["function"]["arguments"]
                if tc.get("id") and not tc_buf[idx]["id"]: tc_buf[idx]["id"] = tc["id"]
            usage = evt.get("usage")
            if usage: _record_usage(usage, api_mode)
        blocks = []
        if reasoning_text: blocks.append({"type": "thinking", "thinking": reasoning_text})
        if content_text: blocks.append({"type": "text", "text": content_text})
        for idx in sorted(tc_buf):
            tc = tc_buf[idx]
            inps = _try_parse_tool_args(tc["args"])
            for i, inp in enumerate(inps):
                bid = tc["id"] or ''
                if len(inps) > 1: bid = f"{bid}_{i}" if bid else f"split_{i}"
                blocks.append({"type": "tool_use", "id": bid, "name": tc["name"], "input": inp})
        return blocks

def _parse_openai_json(data, api_mode="chat_completions"):
    blocks = []
    if api_mode == "responses":
        _record_usage(data.get("usage") or {}, api_mode)
        for item in (data.get("output") or []):
            if item.get("type") == "message":
                for p in (item.get("content") or []):
                    if p.get("type") in ("output_text", "text") and p.get("text"):
                        blocks.append({"type": "text", "text": p["text"]}); yield p["text"]
            elif item.get("type") == "function_call":
                try: args = json.loads(item.get("arguments", "")) if item.get("arguments") else {}
                except json.JSONDecodeError: args = {"_raw": item.get("arguments", "")}
                blocks.append({"type": "tool_use", "id": item.get("call_id", item.get("id", "")),
                               "name": item.get("name", ""), "input": args})
    else:
        _record_usage(data.get("usage") or {}, api_mode)
        msg = (data.get("choices") or [{}])[0].get("message", {})
        reasoning = msg.get("reasoning_content", "")
        if reasoning:
            blocks.append({"type": "thinking", "thinking": reasoning})
        content = msg.get("content", "")
        if content:
            blocks.append({"type": "text", "text": content}); yield content
        for tc in (msg.get("tool_calls") or []):
            fn = tc.get("function", {})
            try: args = json.loads(fn.get("arguments", "")) if fn.get("arguments") else {}
            except json.JSONDecodeError: args = {"_raw": fn.get("arguments", "")}
            blocks.append({"type": "tool_use", "id": tc.get("id", ""), "name": fn.get("name", ""), "input": args})
    return blocks

def _stamp_oai_cache_markers(messages, model):
    """Add cache_control to last 2 user messages for Anthropic models via OAI-compatible relay."""
    ml = model.lower()
    if not any(k in ml for k in ('claude', 'anthropic')): return
    user_idxs = [i for i, m in enumerate(messages) if m.get('role') == 'user']
    for idx in user_idxs[-2:]:
        c = messages[idx].get('content')
        if isinstance(c, str):
            messages[idx] = {**messages[idx], 'content': [{'type': 'text', 'text': c, 'cache_control': {'type': 'ephemeral'}}]}
        elif isinstance(c, list) and c:
            c = list(c); c[-1] = dict(c[-1], cache_control={'type': 'ephemeral'})
            messages[idx] = {**messages[idx], 'content': c}

def _prepare_oai_tools(tools, api_mode="chat_completions"):
    if api_mode == "responses":
        resp_tools = []
        for t in tools:
            if t.get("type") == "function" and "function" in t:
                rt = {"type": "function"}; rt.update(t["function"])
                resp_tools.append(rt)
            else: resp_tools.append(t)
        return resp_tools
    return tools

def _to_responses_input(messages):
    result, pending = [], []
    for msg in messages:
        role = str(msg.get("role", "user")).lower()
        if role == "tool":
            cid = msg.get("tool_call_id") or (pending.pop(0) if pending else f"call_{uuid.uuid4().hex[:8]}")
            result.append({"type": "function_call_output", "call_id": cid, "output": msg.get("content", "")})
            continue
        if role not in ["user", "assistant", "system", "developer"]: role = "user"
        if role == "system": role = "developer"  # Responses API uses 'developer' instead of 'system'
        content = msg.get("content", "")
        text_type = "output_text" if role == "assistant" else "input_text"
        parts = []
        if isinstance(content, str):
            if content: parts.append({"type": text_type, "text": content})
        elif isinstance(content, list):
            for part in content:
                if not isinstance(part, dict): continue
                ptype = part.get("type")
                if ptype == "text":
                    text = part.get("text", "")
                    if text: parts.append({"type": text_type, "text": text})
                elif ptype == "image_url":
                    url = (part.get("image_url") or {}).get("url", "")
                    if url and role != "assistant": parts.append({"type": "input_image", "image_url": url})
        if len(parts) == 0: parts = [{"type": text_type, "text": str(content) if not isinstance(content, list) else '[empty]'}]
        result.append({"role": role, "content": parts})
        pending = []
        for tc in (msg.get("tool_calls") or []):
            f = tc.get("function", {})
            cid = tc.get("id") or f"call_{uuid.uuid4().hex[:8]}"
            pending.append(cid)
            result.append({"type": "function_call", "call_id": cid, "name": f.get("name", ""), "arguments": f.get("arguments", "")})
    return result

def _msgs_claude2oai(messages):
    result = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        blocks = content if isinstance(content, list) else [{"type": "text", "text": str(content)}]
        if role == "assistant":
            text_parts, tool_calls, reasoning = [], [], ""
            for b in blocks:
                if not isinstance(b, dict): continue
                if b.get("type") == "thinking" and b.get("thinking"): reasoning = b["thinking"]
                elif b.get("type") == "text" and b.get("text"): text_parts.append({"type": "text", "text": b.get("text", "")})
                elif b.get("type") == "tool_use":
                    tool_calls.append({
                        "id": b.get("id") or '', "type": "function",
                        "function": {"name": b.get("name", ""), "arguments": json.dumps(b.get("input", {}), ensure_ascii=False)}
                    })
            m = {"role": "assistant"}
            if reasoning: m["reasoning_content"] = reasoning
            if text_parts: m["content"] = text_parts
            elif not tool_calls: m["content"] = "."
            if tool_calls: m["tool_calls"] = tool_calls
            result.append(m)
        elif role == "user":
            text_parts = []
            for b in blocks:
                if not isinstance(b, dict): continue
                if b.get("type") == "tool_result":
                    if text_parts:
                        result.append({"role": "user", "content": text_parts})
                        text_parts = []
                    tr = b.get("content", "")
                    if isinstance(tr, list):
                        tr = "\n".join(x.get("text", "") for x in tr if isinstance(x, dict) and x.get("type") == "text")
                    result.append({"role": "tool", "tool_call_id": b.get("tool_use_id") or '', "content": tr if isinstance(tr, str) else str(tr)})
                elif b.get("type") == "image":
                    src = b.get("source") or {}
                    if src.get("type") == "base64" and src.get("data"):
                        text_parts.append({"type": "image_url", "image_url": {"url": f"data:{src.get('media_type', 'image/png')};base64,{src.get('data', '')}"}})
                elif b.get("type") == "image_url": text_parts.append(b)
                elif b.get("type") == "text" and b.get("text"): text_parts.append({"type": "text", "text": b.get("text", "")})
            if text_parts: result.append({"role": "user", "content": text_parts})
        else: result.append(msg)
    return result

def _keep_claude_block(b): return not isinstance(b, dict) or b.get("type") != "thinking" or b.get("signature")

def _drop_unsigned_thinking(messages):
    for m in messages:
        c = m.get("content")
        if isinstance(c, list): m["content"] = [b for b in c if _keep_claude_block(b)]
    return messages

def _ensure_thinking_blocks(messages, model):
    """Some models (e.g. deepseek) require a thinking block in assistant history."""
    if not model_caps(model)['keep_thinking']: return messages
    for m in messages:
        if m.get("role") != "assistant": continue
        c = m.get("content")
        if not isinstance(c, list): continue
        has_thinking = any(isinstance(b, dict) and b.get("type") == "thinking" for b in c)
        if not has_thinking: m["content"] = [{"type": "thinking", "thinking": "...", "signature": "placeholder"}, *c]
    return messages

def _fix_messages(messages):
    """修复 messages 符合 Claude API：交替、tool_use/tool_result 配对"""
    if not messages: return messages
    _wrap = lambda c: c if isinstance(c, list) else [{"type": "text", "text": str(c)}]
    fixed = []
    for m in messages:
        if fixed and m['role'] == fixed[-1]['role']:
            fixed[-1] = {**fixed[-1], 'content': _wrap(fixed[-1]['content']) + [{"type": "text", "text": "\n"}] + _wrap(m['content'])}; continue
        if fixed and fixed[-1]['role'] == 'assistant' and m['role'] == 'user':
            uses = [b.get('id') for b in fixed[-1].get('content', []) if isinstance(b, dict) and b.get('type') == 'tool_use' and b.get('id')]
            has = {b.get('tool_use_id') for b in _wrap(m['content']) if isinstance(b, dict) and b.get('type') == 'tool_result'}
            miss = [uid for uid in uses if uid not in has]
            if miss: m = {**m, 'content': [{"type": "tool_result", "tool_use_id": uid, "content": "(error)"} for uid in miss] + _wrap(m['content'])}
            orphan = has - set(uses)
            if orphan: m = {**m, 'content': [{"type":"text","text":str(b.get('content',''))} if isinstance(b,dict) and b.get('type')=='tool_result' and b.get('tool_use_id') in orphan else b for b in _wrap(m['content'])]}
        fixed.append(m)
    while fixed and fixed[0]['role'] != 'user': fixed.pop(0)
    return fixed

def openai_tools_to_claude(tools):
    """[{type:'function', function:{name,description,parameters}}] → [{name,description,input_schema}]."""
    result = []
    for t in tools:
        if 'input_schema' in t: result.append(t); continue  # 已是claude格式
        fn = t.get('function', t)
        result.append({'name': fn['name'], 'description': fn.get('description', ''),
            'input_schema': fn.get('parameters', {'type': 'object', 'properties': {}})})
    return result

def tryparse(json_str):
    try: return json.loads(json_str)
    except json.JSONDecodeError: pass
    json_str = json_str.strip().strip('`').replace('json\n', '', 1).strip()
    try: return json.loads(json_str)
    except json.JSONDecodeError: pass
    try: return json.loads(json_str[:-1])
    except json.JSONDecodeError: pass
    if '}' in json_str: json_str = json_str[:json_str.rfind('}') + 1]
    return json.loads(json_str)


# --- response / tool-call value objects + text-fallback tool parsing ---
class MockFunction:
    def __init__(self, name, arguments): self.name, self.arguments = name, arguments

class MockToolCall:
    def __init__(self, name, args, id=''):
        arg_str = json.dumps(args, ensure_ascii=False) if isinstance(args, (dict, list)) else (args or '{}')
        self.function = MockFunction(name, arg_str); self.id = id

class MockResponse:
    def __init__(self, thinking, content, tool_calls, raw, stop_reason='end_turn'):
        self.thinking = thinking; self.content = content          
        self.tool_calls = tool_calls; self.raw = raw
        self.stop_reason = 'tool_use' if tool_calls else stop_reason
    def __repr__(self):    
        return f"<MockResponse thinking={bool(self.thinking)}, content='{self.content}', tools={bool(self.tool_calls)}>"

def _ensure_text_block(blocks):
    """If response has thinking but no text block, inject a synthetic summary from thinking's first line."""
    if any(b.get("type") == "text" for b in blocks): return None
    th = next((b.get("thinking", "") for b in blocks if b.get("type") == "thinking"), "")
    if not th: return None
    line = th.strip().split('\n', 1)[0]
    txt = "<summary>" + (line[:60] + '...' if len(line) > 60 else line) + "</summary>"
    blocks.insert(1, {"type": "text", "text": txt})
    return txt

def _parse_text_tool_calls(content):
    """Fallback: extract tool calls from text when model doesn't use native tool_use blocks."""
    tcs = []
    # try JSON array: [{"type":"tool_use", "name":..., "input":...}]
    _jp = next((p for p in ['[{"type":"tool_use"', '[{"type": "tool_use"'] if p in content), None)
    if _jp and content.endswith('}]'):
        try:
            idx = content.index(_jp); raw = json.loads(content[idx:])
            tcs = [MockToolCall(b["name"], b.get("input", {}), id=b.get("id", "")) for b in raw if b.get("type") == "tool_use"]
            return tcs, content[:idx].strip()
        except json.JSONDecodeError: pass
    # try XML tags: <tool_call>{"name":..., "arguments":...}</tool_call>
    _xp = r"<(?:tool_use|tool_call)>((?:(?!<(?:tool_use|tool_call)>).){15,}?)</(?:tool_use|tool_call)>"
    for s in re.findall(_xp, content, re.DOTALL):
        try:
            d = tryparse(s.strip()); name = d.get('name')
            args = d.get('arguments') or d.get('args') or d.get('input') or {}
            if name: tcs.append(MockToolCall(name, args))
        except json.JSONDecodeError: pass
    if tcs: content = re.sub(_xp, "", content, flags=re.DOTALL).strip()
    return tcs, content
