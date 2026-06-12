"""History layer: tag compression + budget-driven trimming.

Operates on plain message dicts and reads capacity off the session via getattr,
so it depends only on config (for safeprint) — no session/codec imports.
"""
import json, re
from .config import safeprint
print = safeprint

def compress_history_tags(messages, keep_recent=10, max_len=800):
    """Compress <thinking>/<tool_use>/<tool_result> tags in older messages to save tokens.
    Always runs when called — cooldown is owned by the caller (per-session, see trim_messages_history)."""
    _before = sum(len(json.dumps(m, ensure_ascii=False)) for m in messages)
    _pats = {tag: re.compile(rf'(<{tag}>)([\s\S]*?)(</{tag}>)') for tag in ('thinking', 'think', 'tool_use', 'tool_result')}
    _hist_pat = re.compile(r'<(history|key_info|earlier_context)>[\s\S]*?</\1>')
    def _trunc_str(s): return s[:max_len//2] + '\n...[Truncated]...\n' + s[-max_len//2:] if isinstance(s, str) and len(s) > max_len else s
    def _trunc(text):
        text = _hist_pat.sub(lambda m: f'<{m.group(1)}>[...]</{m.group(1)}>', text)
        for pat in _pats.values(): text = pat.sub(lambda m: m.group(1) + _trunc_str(m.group(2)) + m.group(3), text)
        return text
    for i, msg in enumerate(messages):
        if i >= len(messages) - keep_recent: break
        c = msg['content']
        if isinstance(c, str): msg['content'] = _trunc(c)
        elif isinstance(c, list):
            for b in c:
                if not isinstance(b, dict): continue
                t = b.get('type')
                if t == 'text' and isinstance(b.get('text'), str): b['text'] = _trunc(b['text'])
                elif t == 'tool_result':
                    tc = b.get('content')
                    if isinstance(tc, str): b['content'] = _trunc_str(tc)
                    elif isinstance(tc, list):
                        for sub in tc:
                            if isinstance(sub, dict) and sub.get('type') == 'text': sub['text'] = _trunc_str(sub.get('text'))
                elif t == 'tool_use' and isinstance(b.get('input'), dict):
                    for k, v in b['input'].items(): b['input'][k] = _trunc_str(v)
    print(f"[Cut] {_before} -> {sum(len(json.dumps(m, ensure_ascii=False)) for m in messages)}")
    return messages

def _sanitize_leading_user_msg(msg):
    """把 user 消息里的 tool_result 块改写成纯文本，避免孤立引用。
    history 统一使用 Claude content-block 格式：content 是 list of blocks。"""
    msg = dict(msg)  # 浅拷贝外层 dict
    content = msg.get('content')
    if not isinstance(content, list): return msg
    texts = []
    for block in content:
        if not isinstance(block, dict): continue
        if block.get('type') == 'tool_result':
            c = block.get('content', '')
            if isinstance(c, list):  # content 本身也可能是 list[{type:text,text:...}]
                texts.extend(b.get('text', '') for b in c if isinstance(b, dict))
            else: texts.append(str(c))
        elif block.get('type') == 'text': texts.append(block.get('text', ''))
    msg['content'] = [{"type": "text", "text": '\n'.join(t for t in texts if t)}]
    return msg

def trim_messages_history(history, sess):
    cap = sess.context_win * 3
    target = int(cap * getattr(sess, 'trim_keep_rate', 0.6))
    _len = lambda m: len(json.dumps(m, ensure_ascii=False))
    sess._cut_cd = getattr(sess, '_cut_cd', 0) + 1  # 压缩冷却按 session 计数，避免多会话互相消耗
    if sess._cut_cd % getattr(sess, 'cut_msg_interval', 5) == 0: compress_history_tags(history)
    total = sum(_len(m) for m in history)
    print(f'[Debug] Current context: {total} chars, {len(history)} messages.')
    if total <= cap: return
    sess._cut_cd = 0
    compress_history_tags(history, keep_recent=4)
    total = sum(_len(m) for m in history)
    if total <= target: return
    while len(history) > 9 and total > target:
        total -= _len(history.pop(0))
        while history and history[0].get('role') != 'user': total -= _len(history.pop(0))
        if history and history[0].get('role') == 'user':
            old = _len(history[0]); history[0] = _sanitize_leading_user_msg(history[0]); total += _len(history[0]) - old
    print(f'[Debug] Trimmed context, current: {total} chars, {len(history)} messages.')
