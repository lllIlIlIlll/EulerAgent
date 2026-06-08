# stapp3.py Design System Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `frontends/stapp3.py` 的视觉层 100% 对齐 HTML 设计系统（Inter+Space Mono 字体、`#D97757` 强调色、`.msg/.avatar/.bubble` 消息结构、Sidebar 品牌区+会话统计）。

**Architecture:** 用新的 `DESIGN_CSS` 常量（完整映射设计系统 CSS 变量）替换旧的 `ANTHROPIC_CSS`；用 `render_html_message()` 输出完整 `.ga-msg` HTML 结构替换 `st.chat_message()`；Sidebar 注入品牌 HTML 块；保留所有后端功能（流式输出、LLM 切换、System Prompt 注入）不变。

**Tech Stack:** Python 3.10+, Streamlit, `st.markdown(unsafe_allow_html=True)`, Google Fonts (Inter + Space Mono), 可选 `markdown` 包用于 Markdown→HTML 转换。

---

## 文件变更范围

| 文件 | 操作 |
|------|------|
| `frontends/stapp3.py` | 修改 — 全部变更集中于此单文件 |

---

### Task 1: 替换 CSS — 建立设计系统

**Files:**
- Modify: `frontends/stapp3.py` — 删除 `ANTHROPIC_CSS`、`ANTHROPIC_SELECTBOX_SCRIPT`、`build_dynamic_font_css`、`build_dynamic_font_update_script`、`build_header_agent_badge_script`；新增 `DESIGN_CSS`

- [ ] **Step 1: 在文件顶部 import 区域之后，新增 `DESIGN_CSS` 常量**

将下方完整字符串插入（替换原 `ANTHROPIC_CSS = """..."""`，含 `ANTHROPIC_SELECTBOX_SCRIPT`、三个 build_* 函数）：

```python
DESIGN_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Space+Mono&display=swap');

*, *::before, *::after { box-sizing: border-box; }

:root {
  --primary:    #1A1A1A;
  --secondary:  #C9B99A;
  --tertiary:   #D97757;
  --tertiary-h: #E8896A;
  --neutral:    #FAF9F7;
  --surface:    #FFFFFF;
  --border:     #E0DDD8;
  --user-bg:    #F0EDE8;
  --font:       'Inter', sans-serif;
  --mono:       'Space Mono', monospace;
  --r-sm: 6px; --r-md: 12px; --r-lg: 20px; --r-full: 9999px;
  --sp-xs:4px; --sp-sm:8px; --sp-md:16px; --sp-lg:24px; --sp-xl:32px;
}

/* ── Global ── */
body, [data-testid="stAppViewContainer"], .stApp {
    background-color: var(--neutral) !important;
    color: var(--primary) !important;
    font-family: var(--font) !important;
}

/* ── Hide Streamlit chrome ── */
[data-testid="stToolbar"] { visibility: hidden !important; }
[data-testid="stDecoration"], #MainMenu { display: none !important; }
[data-testid="stHeader"], header[data-testid="stHeader"] {
    background-color: var(--neutral) !important;
    border-bottom: 1px solid var(--border) !important;
    height: 0 !important; min-height: 0 !important; overflow: hidden !important;
}

/* ── Sidebar ── */
[data-testid="stSidebar"], section[data-testid="stSidebar"] {
    background-color: var(--neutral) !important;
    border-right: 1px solid var(--border) !important;
    width: 220px !important; min-width: 220px !important; max-width: 220px !important;
}
[data-testid="stSidebarContent"] {
    padding: var(--sp-lg) var(--sp-md) !important;
    display: flex !important; flex-direction: column !important; gap: var(--sp-lg) !important;
}

/* Brand */
.ga-brand {
    display: flex; flex-direction: column; align-items: center;
    gap: 6px; padding-bottom: var(--sp-md); border-bottom: 1px solid var(--border);
}
.ga-brand-logo {
    width: 44px; height: 44px; border-radius: var(--r-md);
    background: var(--tertiary);
    display: flex; align-items: center; justify-content: center;
    font-family: var(--mono); font-size: 1rem; font-weight: 700;
    color: #fff; letter-spacing: 0.04em;
    box-shadow: 0 2px 8px rgba(217,119,87,0.25);
}
.ga-brand-name {
    font-family: var(--mono); font-size: 0.72rem;
    letter-spacing: 0.1em; text-transform: uppercase; color: var(--secondary);
}

/* Sidebar sections */
.ga-sidebar-title {
    font-family: var(--mono); font-size: 0.68rem;
    letter-spacing: 0.05em; text-transform: uppercase;
    color: var(--secondary); padding: 0 var(--sp-sm);
    margin-top: var(--sp-sm);
}
.ga-sidebar-row {
    display: flex; flex-direction: column; gap: 4px;
    padding: var(--sp-sm); border-radius: var(--r-sm);
    background: var(--surface); border: 1px solid var(--border);
    margin-bottom: 4px;
}
.ga-sidebar-row label { font-size: 0.72rem; color: var(--secondary); }
.ga-val { font-size: 0.82rem; font-weight: 500; display: flex; align-items: center; gap: 4px; }
.ga-badge {
    display: inline-flex; align-items: center; gap: 4px;
    font-family: var(--mono); font-size: 0.65rem; letter-spacing: 0.03em;
    padding: 2px 7px; border-radius: var(--r-sm);
    background: rgba(217,119,87,0.1); color: var(--tertiary);
    border: 1px solid rgba(217,119,87,0.25);
}
.ga-badge::before {
    content: ''; width: 5px; height: 5px;
    border-radius: var(--r-full); background: var(--tertiary); display: inline-block;
}

/* Sidebar buttons */
[data-testid="stSidebar"] .stButton > button {
    font-family: var(--font) !important; font-size: 0.82rem !important;
    font-weight: 500 !important; padding: 8px 14px !important;
    border-radius: var(--r-sm) !important;
    border: 1px solid var(--border) !important;
    width: 100% !important; transition: background .2s !important;
    background: transparent !important; color: var(--primary) !important;
}
[data-testid="stSidebar"] .stButton > button:hover { background: var(--user-bg) !important; }
[data-testid="stSidebar"] .stButton > button[kind="primary"],
[data-testid="stSidebar"] .stButton > button[data-testid="stBaseButton-primary"] {
    background: var(--tertiary) !important; color: #fff !important;
    border-color: var(--tertiary) !important;
}
[data-testid="stSidebar"] .stButton > button[kind="primary"]:hover,
[data-testid="stSidebar"] .stButton > button[data-testid="stBaseButton-primary"]:hover {
    background: var(--tertiary-h) !important;
}

/* Sidebar selectbox */
[data-testid="stSidebar"] [data-baseweb="select"] > div {
    background: var(--surface) !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--r-sm) !important;
    box-shadow: none !important;
}
[data-testid="stSidebar"] [data-baseweb="select"] > div:focus-within {
    border-color: var(--tertiary) !important;
    box-shadow: 0 0 0 3px rgba(217,119,87,0.12) !important;
}
[data-testid="stSidebar"] [data-baseweb="select"] span,
[data-testid="stSidebar"] [data-baseweb="select"] div {
    color: var(--primary) !important; font-family: var(--font) !important;
    font-size: 0.82rem !important;
}
[data-testid="stSidebar"] label, [data-testid="stSidebar"] .stMarkdown p,
[data-testid="stSidebar"] p { color: var(--secondary) !important; font-size: 0.72rem !important; }

/* Dropdown list */
[role="listbox"] {
    background: var(--surface) !important; border: 1px solid var(--border) !important;
    border-radius: var(--r-md) !important;
    box-shadow: 0 4px 16px rgba(26,26,26,0.08) !important;
    font-family: var(--font) !important; font-size: 0.82rem !important;
}
[role="option"] {
    color: var(--primary) !important; background: transparent !important;
    border-radius: var(--r-sm) !important;
}
[role="option"]:hover, [role="option"][aria-selected="true"] { background: var(--user-bg) !important; }

/* ── Message HTML classes ── */
.ga-msg {
    display: flex; gap: var(--sp-md); align-items: flex-start;
    padding: 0 48px; margin-bottom: var(--sp-lg);
}
.ga-msg.user { flex-direction: row-reverse; }
.ga-avatar {
    width: 32px; height: 32px; border-radius: var(--r-full); flex-shrink: 0;
    display: flex; align-items: center; justify-content: center;
    font-size: 0.78rem; font-weight: 600; font-family: var(--mono);
}
.ga-avatar.agent { background: var(--tertiary); color: #fff; }
.ga-avatar.user { background: var(--user-bg); border: 1px solid var(--border); color: var(--primary); }
.ga-msg-wrap { display: flex; flex-direction: column; gap: 4px; max-width: 68%; }
.ga-msg.user .ga-msg-wrap { align-items: flex-end; }
.ga-msg-meta { font-family: var(--mono); font-size: 0.65rem; color: var(--secondary); letter-spacing: 0.03em; }
.ga-bubble {
    padding: var(--sp-md) var(--sp-lg); border-radius: var(--r-lg);
    font-size: 0.92rem; line-height: 1.65;
}
.ga-bubble.agent {
    background: var(--surface); border: 1px solid var(--border);
    border-top-left-radius: var(--r-sm);
}
.ga-bubble.user { background: var(--user-bg); border-top-right-radius: var(--r-sm); }
.ga-bubble p { margin: 0; }
.ga-bubble p + p { margin-top: var(--sp-sm); }
.ga-bubble strong { color: var(--tertiary); }
.ga-bubble code {
    font-family: var(--mono); font-size: 0.78rem;
    background: var(--neutral); padding: 2px 6px;
    border-radius: 4px; border: 1px solid var(--border);
}
.ga-bubble pre {
    background: var(--neutral); border: 1px solid var(--border);
    border-radius: var(--r-sm); padding: var(--sp-md); overflow-x: auto;
    margin: var(--sp-sm) 0;
}
.ga-bubble pre code { background: none; border: none; padding: 0; }
.ga-bubble ul, .ga-bubble ol { padding-left: 1.4em; margin: var(--sp-sm) 0; }
.ga-bubble li { margin-bottom: 2px; }

/* System message */
.ga-sys-msg { display: flex; justify-content: center; margin-bottom: var(--sp-lg); }
.ga-sys-msg span {
    font-family: var(--mono); font-size: 0.68rem; color: var(--secondary);
    letter-spacing: 0.03em; background: var(--surface); border: 1px solid var(--border);
    padding: 4px 12px; border-radius: var(--r-full);
}

/* Typing indicator */
.ga-typing { display: flex; gap: 5px; align-items: center; padding: 4px 2px; }
.ga-typing span {
    width: 6px; height: 6px; border-radius: var(--r-full);
    background: var(--secondary); animation: ga-bounce 1.2s infinite; display: inline-block;
}
.ga-typing span:nth-child(2) { animation-delay: .2s; }
.ga-typing span:nth-child(3) { animation-delay: .4s; }
@keyframes ga-bounce { 0%,60%,100% { transform: translateY(0); } 30% { transform: translateY(-5px); } }

/* ── Chat input ── */
[data-testid="stChatInput"] > div {
    background: var(--surface) !important; border: 1px solid var(--border) !important;
    border-radius: var(--r-md) !important;
}
[data-testid="stChatInput"] > div:focus-within {
    border-color: var(--tertiary) !important;
    box-shadow: 0 0 0 3px rgba(217,119,87,0.12) !important;
}
[data-testid="stChatInput"] textarea {
    font-family: var(--font) !important; font-size: 0.92rem !important;
    color: var(--primary) !important; background: transparent !important;
    caret-color: var(--primary) !important;
}
[data-testid="stChatInput"] textarea::placeholder { color: var(--secondary) !important; opacity: 0.8 !important; }
[data-testid="stChatInput"] button, [data-testid="stChatInputSubmitButton"] {
    background: var(--tertiary) !important; border-radius: var(--r-sm) !important;
    color: #fff !important;
}
[data-testid="stChatInput"] button:hover { background: var(--tertiary-h) !important; }

/* Input hint */
[data-testid="stBottomBlockContainer"] { background: var(--neutral) !important; }
[data-testid="stBottomBlockContainer"]::after {
    content: 'ENTER 发送  ·  SHIFT+ENTER 换行';
    display: block; text-align: center;
    font-family: 'Space Mono', monospace;
    font-size: 0.65rem; color: #C9B99A;
    letter-spacing: 0.03em; margin-top: 4px; padding-bottom: 8px;
}

/* Stop button */
.stop-btn-anchor { display: none !important; }
[data-testid="stElementContainer"]:has(.stop-btn-anchor) {
    height: 0 !important; min-height: 0 !important;
    margin: 0 !important; padding: 0 !important; overflow: visible !important;
}
[data-testid="stVerticalBlock"]:has(.stop-btn-anchor):not(:has([data-testid="stChatMessage"])) {
    position: fixed !important; bottom: 5.75rem !important;
    left: 50% !important; transform: translateX(-50%) !important;
    z-index: 1000 !important; width: auto !important; background: transparent !important;
    pointer-events: none !important; gap: 0 !important;
}
[data-testid="stVerticalBlock"]:has(.stop-btn-anchor):not(:has([data-testid="stChatMessage"])) > * { pointer-events: auto !important; }
[data-testid="stVerticalBlock"]:has(.stop-btn-anchor):not(:has([data-testid="stChatMessage"])) [data-testid="stButton"] > button {
    border-radius: var(--r-full) !important;
    background: rgba(217,119,87,0.95) !important; border-color: rgba(217,119,87,0.95) !important;
    color: #fff !important; font-size: 0.84rem !important;
    padding: 0.35rem 1.1rem !important; box-shadow: 0 2px 8px rgba(0,0,0,0.12) !important;
}

/* ── Main content area ── */
[data-testid="stMainBlockContainer"] {
    padding-top: var(--sp-xl) !important;
    padding-left: 0 !important; padding-right: 0 !important;
    max-width: 100% !important;
}
/* 消除 st.markdown 默认 margin，让 ga-msg 自己控制间距 */
[data-testid="stMarkdownContainer"] { margin: 0 !important; padding: 0 !important; }
[data-testid="stElementContainer"] { margin-bottom: 0 !important; }

/* ── Scrollbar ── */
::-webkit-scrollbar { width: 4px; height: 4px; }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: var(--r-full); }
::-webkit-scrollbar-track { background: transparent; }

/* ── Misc ── */
hr { border-color: var(--border) !important; }
a { color: var(--tertiary) !important; }
a:hover { color: var(--tertiary-h) !important; }
</style>
"""
```

- [ ] **Step 2: 删除以下旧常量和函数（全部替换为 `DESIGN_CSS`）**

删除：
- `ANTHROPIC_CSS = """..."""`（约 24–657 行）
- `ANTHROPIC_SELECTBOX_SCRIPT = """..."""`（约 659–798 行）
- `def build_dynamic_font_css(scale_percent: float) -> str:`（约 811–828 行）
- `def build_dynamic_font_update_script(scale_percent: float) -> str:`（约 831–850 行）
- `def build_header_agent_badge_script() -> str:`（约 853–942 行）

- [ ] **Step 3: 验证语法正确**

```bash
cd /Users/x403/EulerAgent/.worktrees/release-v3.0.0
python -c "import ast; ast.parse(open('frontends/stapp3.py').read()); print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add frontends/stapp3.py
git commit -m "style: replace ANTHROPIC_CSS with design system DESIGN_CSS (Inter/SpaceMono, D97757)"
```

---

### Task 2: 消息渲染 — 自定义 HTML Bubble

**Files:**
- Modify: `frontends/stapp3.py` — 新增 `_md_to_html()`、`render_html_message()`、`render_html_sys_message()`、`render_typing_html()`；删除旧 `render_message()`

- [ ] **Step 1: 在 `init()` 函数之前，新增 markdown 转换和消息渲染函数**

```python
try:
    import markdown as _md_lib
    def _md_to_html(text: str) -> str:
        return _md_lib.markdown(text, extensions=['nl2br', 'fenced_code', 'tables'])
except ImportError:
    import re as _re
    def _md_to_html(text: str) -> str:
        t = html.escape(text)
        t = _re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', t, flags=_re.DOTALL)
        t = _re.sub(r'`([^`]+)`', r'<code>\1</code>', t)
        t = t.replace('\n\n', '</p><p>').replace('\n', '<br>')
        return f'<p>{t}</p>' if t else ''


def render_html_message(role: str, content: str, ts: str = '') -> None:
    is_user = role == 'user'
    cls = 'user' if is_user else 'agent'
    avatar_text = '你' if is_user else 'G'
    meta = ts if is_user else f'Euler Agent · {ts}'
    content_html = html.escape(content) if is_user else _md_to_html(content)
    st.markdown(f"""
<div class="ga-msg {cls}">
  <div class="ga-avatar {cls}">{avatar_text}</div>
  <div class="ga-msg-wrap">
    <span class="ga-msg-meta">{meta}</span>
    <div class="ga-bubble {cls}">{content_html}</div>
  </div>
</div>""", unsafe_allow_html=True)


def render_html_sys_message(text: str) -> None:
    st.markdown(
        f'<div class="ga-sys-msg"><span>{html.escape(text)}</span></div>',
        unsafe_allow_html=True
    )


def render_typing_html() -> None:
    st.markdown("""
<div class="ga-msg">
  <div class="ga-avatar agent">G</div>
  <div class="ga-msg-wrap">
    <span class="ga-msg-meta">Euler Agent · 正在输入…</span>
    <div class="ga-bubble agent">
      <div class="ga-typing"><span></span><span></span><span></span></div>
    </div>
  </div>
</div>""", unsafe_allow_html=True)
```

- [ ] **Step 2: 删除旧 `render_message()` 函数**

删除：
```python
def render_message(role, content, ts='', unsafe_allow_html=True):
    with st.chat_message(role):
        if ts: st.markdown(f'<div class="msg-timestamp">{ts}</div>', unsafe_allow_html=True)
        st.markdown(content, unsafe_allow_html=unsafe_allow_html)
```

- [ ] **Step 3: 更新 `render_streaming_area()` 使用新渲染器**

将 `render_streaming_area()` 替换为：

```python
def render_streaming_area():
    if not st.session_state.streaming: return
    with st.container():
        st.markdown('<span class="stop-btn-anchor"></span>', unsafe_allow_html=True)
        if st.button("⏹️ 停止生成", type="primary"):
            agent.abort(); st.session_state.stopping = True
            st.toast("已发送停止信号"); st.rerun()
    reply_ts = st.session_state.reply_ts
    with st.empty().container():
        partial = st.session_state.partial_response
        if partial:
            segments = _get_response_segments(partial)
            for i, seg in enumerate(segments):
                render_html_message("assistant", seg + ("" if i < len(segments) - 1 else "▌"), ts=reply_ts)
        else:
            render_typing_html()
    if poll_agent_output(): finish_streaming_message()
    else: time.sleep(0.2)
    st.rerun()
```

- [ ] **Step 4: 更新主渲染循环**

将：
```python
for msg in st.session_state.messages: render_message(msg["role"], msg["content"], ts=msg.get("time", ""), unsafe_allow_html=True)
```

替换为：
```python
for msg in st.session_state.messages:
    render_html_message(msg["role"], msg["content"], ts=msg.get("time", ""))
```

- [ ] **Step 5: 验证语法正确**

```bash
python -c "import ast; ast.parse(open('frontends/stapp3.py').read()); print('OK')"
```

Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add frontends/stapp3.py
git commit -m "feat: custom HTML bubble renderer (render_html_message, typing indicator, sys-msg)"
```

---

### Task 3: Sidebar 重构 — 品牌块 + 会话统计

**Files:**
- Modify: `frontends/stapp3.py` — 更新 `init_session_state()`、`render_sidebar()`、`finish_streaming_message()`

- [ ] **Step 1: 在 `init_session_state()` 中新增统计字段**

将现有函数替换为：

```python
def init_session_state():
    for key, value in {
        'agent_name': 'EulerAgent', 'streaming': False, 'stopping': False,
        'display_queue': None, 'partial_response': '', 'reply_ts': '',
        'current_prompt': '', 'selected_llm_idx': agent.llm_no,
        'autonomous_enabled': False, 'messages': [],
        'session_start_time': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'token_count': 0, 'conversation_rounds': 0,
    }.items():
        st.session_state.setdefault(key, value)
```

- [ ] **Step 2: 在 `finish_streaming_message()` 末尾增加轮次计数**

将现有函数替换为：

```python
def finish_streaming_message():
    reply_ts = st.session_state.reply_ts
    st.session_state.messages.extend(
        {"role": "assistant", "content": seg, "time": reply_ts}
        for seg in _get_response_segments(st.session_state.partial_response)
    )
    st.session_state.last_reply_time = int(time.time())
    st.session_state.conversation_rounds += 1
    st.session_state.partial_response = st.session_state.reply_ts = st.session_state.current_prompt = ''
```

- [ ] **Step 3: 完整替换 `render_sidebar()` 函数**

```python
@st.fragment
def render_sidebar():
    # Brand block
    st.markdown("""
<div class="ga-brand">
  <div class="ga-brand-logo">GA</div>
  <span class="ga-brand-name">Euler Agent</span>
</div>""", unsafe_allow_html=True)

    # LLM info
    st.markdown('<div class="ga-sidebar-title">设置</div>', unsafe_allow_html=True)
    llm_options, current_idx = agent.list_llms(), agent.llm_no
    llm_name = agent.get_llm_name() or ''
    st.markdown(f"""
<div class="ga-sidebar-row">
  <label>当前使用的 LLM</label>
  <div class="ga-val"><span class="ga-badge">{html.escape(llm_name)}</span></div>
</div>""", unsafe_allow_html=True)

    # LLM selector
    st.markdown('<div class="ga-sidebar-title">选择链路</div>', unsafe_allow_html=True)
    llm_labels = {idx: f"{idx}: {(name or '').strip()}" for idx, name, _ in llm_options}
    selected_idx = st.selectbox(
        "选择链路",
        [idx for idx, _, _ in llm_options],
        index=next((i for i, (idx, _, _) in enumerate(llm_options) if idx == current_idx), 0),
        format_func=llm_labels.get,
        key="sidebar_llm_select",
        label_visibility="collapsed",
    )
    if selected_idx != current_idx:
        agent.next_llm(selected_idx)
        st.session_state.selected_llm_idx = selected_idx
        st.toast(f"已切换到链路：{llm_labels[selected_idx]}")
        st.rerun()

    # Buttons
    if st.button("↺ 重新注入 System Prompt", key="btn_reinject"):
        agent.llmclient.last_tools = ''
        st.toast("下次将重新注入 System Prompt")
    if st.button("＋ 新建对话", type="primary", key="btn_new_chat"):
        st.session_state.messages = []
        st.session_state.conversation_rounds = 0
        st.session_state.token_count = 0
        st.session_state.session_start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        st.rerun()

    # Session info at bottom
    st.divider()
    st.markdown('<div class="ga-sidebar-title">会话信息</div>', unsafe_allow_html=True)
    token_str = f"{st.session_state.token_count:,}" if st.session_state.token_count else "—"
    rounds_str = str(st.session_state.conversation_rounds)
    st.markdown(f"""
<div class="ga-sidebar-row"><label>已用 Token</label><div class="ga-val">{token_str}</div></div>
<div class="ga-sidebar-row"><label>对话轮次</label><div class="ga-val">{rounds_str}</div></div>
""", unsafe_allow_html=True)
```

- [ ] **Step 4: 验证语法正确**

```bash
python -c "import ast; ast.parse(open('frontends/stapp3.py').read()); print('OK')"
```

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add frontends/stapp3.py
git commit -m "feat: sidebar brand block, new-chat button, token/rounds session stats"
```

---

### Task 4: 主入口整合 — CSS 注入 + 会话初始化消息

**Files:**
- Modify: `frontends/stapp3.py` — 更新 `st.set_page_config`、主注入代码块、欢迎消息渲染

- [ ] **Step 1: 更新 `st.set_page_config`**

将：
```python
st.set_page_config(page_title="Cowork", layout="wide")
```

替换为：
```python
st.set_page_config(page_title="Euler Agent", layout="wide")
```

- [ ] **Step 2: 替换旧 CSS/JS 注入代码块**

将：
```python
# Inject Anthropic theme
st.markdown(ANTHROPIC_CSS, unsafe_allow_html=True)
st.markdown(build_dynamic_font_css(110.0), unsafe_allow_html=True)
_embed_html(ANTHROPIC_SELECTBOX_SCRIPT, height=0, width=0)
_embed_html(build_header_agent_badge_script(), height=0, width=0)

st.session_state.agent_name = 'Euler Agent'
with st.chat_message("assistant"):
    st.markdown(f'<div class="msg-timestamp">{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</div>', unsafe_allow_html=True)
    st.write("欢迎使用EulerAgent~")
```

替换为：
```python
st.markdown(DESIGN_CSS, unsafe_allow_html=True)

# Session establishment message (fixed start time)
render_html_sys_message(f"{st.session_state.session_start_time} · 会话已建立")
render_html_message(
    "assistant",
    "欢迎使用 EulerAgent～ 我已准备就绪，请输入您的指令。",
    ts=st.session_state.session_start_time,
)
```

- [ ] **Step 3: 删除不再使用的 `_embed_html` import 代码块**

删除（如果 `_embed_html` 不再有其他调用）：
```python
try:
    from streamlit import iframe as _st_iframe  # 1.56+
    _embed_html = lambda html, **kw: _st_iframe(html, **{k: max(v, 1) if isinstance(v, int) else v for k, v in kw.items()})
except (ImportError, AttributeError):
    from streamlit.components.v1 import html as _embed_html  # ≤1.55
```

- [ ] **Step 4: 检查全文中是否还有 `render_message` / `_embed_html` / `ANTHROPIC` 残留引用**

```bash
grep -n "render_message\|_embed_html\|ANTHROPIC\|build_dynamic\|build_header" frontends/stapp3.py
```

Expected: 无输出（全部已删除）

- [ ] **Step 5: 验证语法**

```bash
python -c "import ast; ast.parse(open('frontends/stapp3.py').read()); print('OK')"
```

Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add frontends/stapp3.py
git commit -m "refactor: wire DESIGN_CSS injection, session init message, remove legacy embed helpers"
```

---

### Task 5: Token 计数 + 最终清理

**Files:**
- Modify: `frontends/stapp3.py` — `poll_agent_output()` 接收 token 信息，移除孤立死代码

- [ ] **Step 1: 更新 `poll_agent_output()` 以解析 token 信息**

将现有函数替换为：

```python
def poll_agent_output(max_items=20):
    q = st.session_state.display_queue
    if q is None:
        st.session_state.streaming = False
        return False
    done = False
    for _ in range(max_items):
        try:
            item = q.get_nowait()
        except queue.Empty:
            break
        if 'next' in item: st.session_state.partial_response = item['next']
        if 'tokens' in item: st.session_state.token_count = item['tokens']
        if 'done' in item:
            st.session_state.partial_response = item['done']
            done = True
            break
    if done:
        st.session_state.streaming = st.session_state.stopping = False
        st.session_state.display_queue = None
    return done
```

- [ ] **Step 2: 最终视觉核查清单**

运行 `streamlit run frontends/stapp3.py` 并逐项核对：

- [ ] 字体：正文为 Inter，代码/meta/badge 为 Space Mono
- [ ] 品牌：Sidebar 顶部显示橙色 "GA" logo + "GENERIC AGENT" 字样
- [ ] 设置区：LLM 名称显示在 `ga-badge`（橙色胶囊），含亮点
- [ ] 链路选择：下拉框样式匹配设计（白色背景，`#E0DDD8` 边框，焦点时橙色发光）
- [ ] 按钮：`↺ 重新注入` 次要样式（透明背景），`＋ 新建对话` 主要样式（#D97757）
- [ ] 会话信息：Token 与对话轮次显示在 Sidebar 底部卡片中
- [ ] 系统消息：顶部胶囊显示 "YYYY-MM-DD HH:MM:SS · 会话已建立"
- [ ] Agent 消息：左侧橙色 "G" 圆形头像，白色气泡，左上角小圆角
- [ ] User 消息：右侧浅色 "你" 头像，`#F0EDE8` 气泡，右上角小圆角
- [ ] 打字动画：三点弹跳，无文字内容时显示
- [ ] 输入框：白色背景，12px 圆角，焦点时橙色发光环
- [ ] 提示文字：输入框下方 "ENTER 发送 · SHIFT+ENTER 换行"

- [ ] **Step 3: Final commit**

```bash
git add frontends/stapp3.py
git commit -m "refactor: stapp3 100% aligned to design system — Inter/SpaceMono, #D97757, custom HTML bubbles"
```
