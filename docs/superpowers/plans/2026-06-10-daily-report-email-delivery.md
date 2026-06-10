# Daily Report Email Delivery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `do_send_email` tool + parameterized scheduler prompt injection so scheduled daily-report tasks can deliver a Word (.docx) attachment to a recipient list. Also clean `ekey.py` from repo tracking and ship a `ekey.template.py` for collaborators.

**Architecture:** Reuse the existing agent loop and scheduler. New code lives in three places: a `do_send_email` method on `EulerAgentHandler` (with smtplib + retry), a 4-line f-string extension in `reflect/scheduler.py` for prompt injection, and `ekey.template.py` for credentials. pandoc (system binary) does `.md → .docx` via `code_run` — no new Python deps.

**Tech Stack:** Python 3.10-3.13 stdlib (`smtplib`, `email.mime`, `email.utils`), external `pandoc`, pytest for tests, no new pip deps.

**Spec:** `docs/superpowers/specs/2026-06-10-daily-report-email-delivery-design.md` (commit `29b5e03`)

**Decomposition:** Three PRs.
- **PR-1** (Tasks 1-3): ekey cleanup + template + ekey_loader tolerance — independently mergeable
- **PR-2** (Tasks 4-8): do_send_email tool + schema + scheduler prompt + sop update + tests
- **PR-3** (Task 9, optional): example task JSON for `sche_tasks/`

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `ekey.template.py` | new | EMAIL_SMTP credential template (committed) |
| `ekey.py` | git rm --cached | real credentials (untracked, .gitignore already lists it) |
| `core/ekey_loader.py` | new | tolerant `from ekey import EKEY` wrapper |
| `core/ea.py` | modify | add `do_send_email`, import ekey_loader |
| `core/agent_loop.py` | none | (untouched) |
| `assets/tools_schema.json` | modify | add `send_email` tool declaration |
| `assets/tools_schema_cn.json` | modify | add Chinese description variant |
| `reflect/scheduler.py` | modify | 4-line prompt injection for `recipients` |
| `memory/daily_report_sop.md` | modify | append "Word 附件输出" section |
| `README.md` | modify | add `cp ekey.template.py ekey.py` line |
| `CONTRIBUTING.md` | modify | add `cp ekey.template.py ekey.py` line |
| `tests/test_send_email.py` | new | unit tests for do_send_email |
| `tests/test_scheduler_inject.py` | new | unit test for scheduler prompt injection |
| `sche_tasks/example_daily_email.json` | new | sample task JSON (committed, no real emails) |

---

## PR-1: ekey cleanup + template

### Task 1: Create `ekey.template.py`

**Files:**
- Create: `ekey.template.py`

- [ ] **Step 1: Write the file**

Write to `/Users/x403/EulerAgent/ekey.template.py`:

```python
# ekey.template.py
# 真实凭证文件 ekey.py 已在 .gitignore，请勿提交。
# 首次使用：cp ekey.template.py ekey.py 并填写真实值。

EKEY = {
    "LLM": {
        # 现有 LLM 段保持原样，不在本文档变更范围。
        # 真实 ekey.py 中此段含 ANTHROPIC_API_KEY / OPENAI_API_KEY 等。
    },
    "EMAIL_SMTP": {
        "host":     "smtp.gmail.com",   # SMTP 服务器
        "port":     587,                # 587 = STARTTLS；465 = SSL
        "user":     "<your_email>",     # 完整邮箱地址
        "auth_code":"<app_password>",   # Gmail/QQ/163 的应用专用密码（非登录密码）
        "use_tls":  True,               # True = STARTTLS on 587；False = SSL on 465
        "from_name":"EulerAgent Bot",   # 发件人显示名
    },
}
```

- [ ] **Step 2: Verify file is committed-friendly**

Run: `git check-ignore ekey.py && echo "ekey.py correctly ignored"`
Run: `git status --porcelain ekey.template.py`
Expected: First command prints `ekey.py correctly ignored`. Second command prints `?? ekey.template.py` (untracked, not ignored — good).

- [ ] **Step 3: Commit**

```bash
git add ekey.template.py
git commit -m "feat(ekey): add EMAIL_SMTP template for email delivery"
```

---

### Task 2: Remove `ekey.py` from repo tracking

**Files:**
- Modify: repo index (no source file changes)

- [ ] **Step 1: Verify ekey.py is currently tracked**

Run: `git ls-files ekey.py`
Expected: prints `ekey.py` (file is in index). If empty, skip to Step 3.

- [ ] **Step 2: Remove from index, keep on disk**

Run: `git rm --cached ekey.py`
Expected: prints `rm 'ekey.py'`. Local `ekey.py` file is preserved.

- [ ] **Step 3: Verify .gitignore already covers it**

Run: `grep -F "ekey.py" .gitignore`
Expected: prints a line containing `ekey.py`. If absent, append: `printf "ekey.py\n" >> .gitignore`.

- [ ] **Step 4: Commit**

```bash
git add .gitignore 2>/dev/null || true
git add -u ekey.py
git commit -m "chore: untrack ekey.py (now via ekey.template.py)"
```

---

### Task 3: Add tolerant `core/ekey_loader.py`

**Files:**
- Create: `core/ekey_loader.py`

- [ ] **Step 1: Write the file**

Write to `/Users/x403/EulerAgent/core/ekey_loader.py`:

```python
"""Tolerant ekey loader: missing file or empty file → empty dict, never raises.
Existing callers should `from ekey_loader import EKEY` instead of `from ekey import EKEY`.
"""
try:
    from ekey import EKEY  # type: ignore
except Exception:
    EKEY = {}
```

- [ ] **Step 2: Smoke test**

Run: `cd /Users/x403/EulerAgent/core && python -c "from ekey_loader import EKEY; print(type(EKEY))"`
Expected: prints `<class 'dict'>` (works whether ekey.py exists or not).

- [ ] **Step 3: Commit**

```bash
git add core/ekey_loader.py
git commit -m "feat(ekey): add tolerant ekey_loader for missing-file resilience"
```

---

## PR-2: do_send_email tool + integration

### Task 4: Add `do_send_email` to `core/ea.py`

**Files:**
- Modify: `core/ea.py` (add import + new method)
- Test: `tests/test_send_email.py`

- [ ] **Step 1: Write the failing test**

Create `/Users/x403/EulerAgent/tests/test_send_email.py`:

```python
"""Contract: do_send_email — success path, retry, validation."""
import os, sys, unittest, types
from unittest.mock import patch, MagicMock, mock_open

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'core'))
import _bootstrap  # noqa: F401
import ea as ea_mod
from agent_loop import StepOutcome


SMTP = {
    "host":"smtp.test", "port":587, "user":"bot@test.com",
    "auth_code":"abcd", "use_tls":True, "from_name":"Bot",
}

class _Args(dict):
    def get(self, k, d=None):
        if k in self: return self[k]
        return super().get(k, d)

class HandlerHarness:
    """Minimal stand-in invoking do_send_email through its real signature."""
    def __init__(self):
        self.cwd = "/tmp"
        self.parent = types.SimpleNamespace(history_info="")
    def __getattr__(self, name):
        return getattr(ea_mod.EulerAgentHandler, name).__get__(self, type(self))


def make_handler():
    h = HandlerHarness()
    return h


class TestSendEmail(unittest.TestCase):

    def _args(self, **kw):
        a = _Args({
            "to":["a@x.com","b@x.com"],
            "subject":"hi",
            "body":"hello",
            "attachments":[],
        })
        a.update(kw); return a

    def test_missing_email_smtp_raises(self):
        h = make_handler()
        with patch("ea.EKEY", {}):
            with self.assertRaises(KeyError):
                gen = h.do_send_email(self._args(), response=None)
                list(gen)  # exhaust generator

    def test_rejects_bad_attachment_extension(self):
        h = make_handler()
        bad = _Args({"to":["a@x.com"], "subject":"s", "body":"b",
                     "attachments":["/tmp/x.exe"]})
        with patch("ea.EKEY", SMTP):
            with self.assertRaises(ValueError):
                gen = h.do_send_email(bad, response=None)
                list(gen)

    def test_missing_attachment_file_raises(self):
        h = make_handler()
        bad = _Args({"to":["a@x.com"], "subject":"s", "body":"b",
                     "attachments":["/tmp/nonexistent_zzz_12345.docx"]})
        with patch("ea.EKEY", SMTP):
            with self.assertRaises(FileNotFoundError):
                gen = h.do_send_email(bad, response=None)
                list(gen)

    def test_success_yields_confirmation(self):
        h = make_handler()
        # touch a real file
        path = "/tmp/_test_attach.docx"
        with open(path, "wb") as f: f.write(b"PK\x03\x04 fake docx")
        try:
            args = _Args({"to":["a@x.com"], "subject":"s", "body":"b",
                          "attachments":[path]})
            with patch("ea.EKEY", SMTP), \
                 patch("ea.smtplib.SMTP") as MockSMTP:
                inst = MagicMock()
                MockSMTP.return_value.__enter__.return_value = inst
                yields, outcome = [], None
                gen = h.do_send_email(args, response=None)
                try:
                    while True: yields.append(next(gen))
                except StopIteration as e: outcome = e.value
            self.assertTrue(any("已投递" in y for y in yields),
                            f"no success yield, got {yields!r}")
            self.assertIsInstance(outcome, StepOutcome)
            self.assertFalse(outcome.should_exit)
            inst.login.assert_called_once()
            inst.sendmail.assert_called_once()
        finally:
            os.remove(path)

    def test_auth_error_retries_three_times(self):
        h = make_handler()
        path = "/tmp/_test_attach2.docx"
        with open(path, "wb") as f: f.write(b"PK\x03\x04 fake")
        try:
            args = _Args({"to":["a@x.com"], "subject":"s", "body":"b",
                          "attachments":[path]})
            with patch("ea.EKEY", SMTP), \
                 patch("ea.smtplib.SMTP") as MockSMTP, \
                 patch("ea.time.sleep") as msleep:
                inst = MagicMock()
                inst.login.side_effect = Exception("auth boom")
                MockSMTP.return_value.__enter__.return_value = inst
                yields = []
                gen = h.do_send_email(args, response=None)
                try:
                    while True: yields.append(next(gen))
                except StopIteration: pass
            self.assertEqual(inst.login.call_count, 3,
                             f"expected 3 retries, got {inst.login.call_count}")
            self.assertEqual(msleep.call_count, 2,
                             "expected 2 sleeps between 3 attempts (1s, 3s)")
            self.assertTrue(any("失败" in y for y in yields),
                            f"no failure yield, got {yields!r}")
        finally:
            os.remove(path)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test, verify it fails**

Run: `cd /Users/x403/EulerAgent && python -m pytest tests/test_send_email.py -v`
Expected: ImportError or AttributeError because `do_send_email` doesn't exist yet.

- [ ] **Step 3: Add imports to `core/ea.py`**

At the top of `/Users/x403/EulerAgent/core/ea.py` (after existing imports), add:

```python
import smtplib, time
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders
from email.utils import formataddr
from ekey_loader import EKEY
```

- [ ] **Step 4: Add `do_send_email` method to `EulerAgentHandler`**

Find the line near `def do_ask_user` in `core/ea.py` (around L308). Add this new method just before it:

```python
    def do_send_email(self, args, response):
        """通过 SMTP 投递邮件，支持 .docx / .md / .pdf 附件。重试 3 次后失败则把状态写入附件文件头。
        args = {"to":[...], "subject":..., "body":..., "attachments":[...]}
        """
        smtp = EKEY.get("EMAIL_SMTP")
        if not smtp:
            raise KeyError("ekey 缺 EMAIL_SMTP 段 — cp ekey.template.py ekey.py 并填写")
        to      = args.get("to") or []
        subject = args.get("subject", "")
        body    = args.get("body", "")
        attachs = args.get("attachments") or []
        if not to or not subject:
            raise ValueError("to/subject 必填")
        for p in attachs:
            if not os.path.isfile(p):
                raise FileNotFoundError(f"附件不存在: {p}")
            if not p.lower().endswith((".docx", ".md", ".pdf")):
                raise ValueError(f"附件类型不支持: {p}")

        msg = MIMEMultipart()
        msg["From"]    = formataddr((smtp["from_name"], smtp["user"]))
        msg["To"]      = ", ".join(to)
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain", "utf-8"))
        for p in attachs:
            with open(p, "rb") as f:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", f'attachment; filename="{os.path.basename(p)}"')
            msg.attach(part)

        last_err = None
        for attempt in range(1, 4):
            try:
                with smtplib.SMTP(smtp["host"], smtp["port"], timeout=30) as s:
                    if smtp.get("use_tls", True):
                        s.starttls()
                    s.login(smtp["user"], smtp["auth_code"])
                    s.sendmail(smtp["user"], to, msg.as_string())
                last_err = None
                break
            except (smtplib.SMTPException, OSError) as e:
                last_err = e
                yield f"[email] attempt {attempt}/3 failed: {e}\n"
                if attempt < 3:
                    time.sleep(3 ** (attempt - 1))  # 1s, 3s

        if last_err is None:
            yield f"邮件已投递：{len(to)} 收件人\n"
        else:
            yield f"邮件失败：{last_err}\n"
        return StepOutcome(
            data={"recipients": to, "subject": subject, "ok": last_err is None},
            next_prompt=None,
            should_exit=False,
        )
```

- [ ] **Step 5: Run test, verify it passes**

Run: `cd /Users/x403/EulerAgent && python -m pytest tests/test_send_email.py -v`
Expected: 5 tests pass. If `do_no_tool` warnings, ignore.

- [ ] **Step 6: Commit**

```bash
git add core/ea.py tests/test_send_email.py
git commit -m "feat(email): add do_send_email tool with smtplib + 3-retry"
```

---

### Task 5: Register `send_email` in `assets/tools_schema.json`

**Files:**
- Modify: `assets/tools_schema.json`

- [ ] **Step 1: Inspect current schema structure**

Run: `python -c "import json; d=json.load(open('/Users/x403/EulerAgent/assets/tools_schema.json')); print(type(d).__name__, len(d) if hasattr(d,'__len__') else ''); print(list(d.keys())[:5] if isinstance(d,dict) else d[0])"`
Expected: prints structure (`list` of tool dicts, or `dict` with `tools` key). Use this to find where to add the new tool.

- [ ] **Step 2: Add `send_email` tool entry**

Based on Step 1 structure, add a new tool entry (use Edit with `replace_all=false`):

```json
    {
      "name": "send_email",
      "description": "Send email via SMTP. Supports .docx/.md/.pdf attachments. Retries 3x on failure. Reads EMAIL_SMTP from ekey. Required: to (list), subject, body. Optional: attachments (list of absolute paths).",
      "input_schema": {
        "type": "object",
        "properties": {
          "to": {
            "type": "array",
            "items": {"type": "string"},
            "description": "收件人邮箱地址列表"
          },
          "subject": {"type": "string", "description": "邮件主题"},
          "body":    {"type": "string", "description": "纯文本正文"},
          "attachments": {
            "type": "array",
            "items": {"type": "string"},
            "description": "附件绝对路径列表（支持 .docx / .md / .pdf）"
          }
        },
        "required": ["to", "subject", "body"]
      }
    }
```

If the schema is a list of tools, append this entry to the list. If it's a dict with a `tools` key, append to `d["tools"]`.

- [ ] **Step 3: Validate JSON**

Run: `python -c "import json; d=json.load(open('/Users/x403/EulerAgent/assets/tools_schema.json')); names=[t.get('name') for t in (d if isinstance(d,list) else d.get('tools',[]))]; print('send_email' in names)"`
Expected: prints `True`.

- [ ] **Step 4: Mirror to `tools_schema_cn.json`**

Run: `python -c "import json; d=json.load(open('/Users/x403/EulerAgent/assets/tools_schema_cn.json')); print(type(d).__name__); print(list(d.keys())[:5] if isinstance(d,dict) else len(d))"`
Add the same tool entry to `tools_schema_cn.json` (Chinese description variant). The JSON shape is parallel to tools_schema.json — add it to the same position.

- [ ] **Step 5: Validate both files**

Run: `python -c "import json; [json.load(open(f'/Users/x403/EulerAgent/assets/tools_schema{n}.json')) for n in ['','_cn']]; print('OK')"`
Expected: prints `OK`.

- [ ] **Step 6: Commit**

```bash
git add assets/tools_schema.json assets/tools_schema_cn.json
git commit -m "feat(email): register send_email in tools_schema (en + cn)"
```

---

### Task 6: Inject `recipients` into scheduler prompt

**Files:**
- Modify: `reflect/scheduler.py` (4 lines added inside `check()`)
- Test: `tests/test_scheduler_inject.py`

- [ ] **Step 1: Write the failing test**

Create `/Users/x403/EulerAgent/tests/test_scheduler_inject.py`:

```python
"""Contract: scheduler.check() injects recipients block into task prompt when present."""
import os, sys, json, tempfile, unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'reflect'))

import scheduler


class TestSchedulerInject(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        scheduler.TASKS = self.tmpdir
        scheduler.DONE  = os.path.join(self.tmpdir, "done")
        os.makedirs(scheduler.DONE, exist_ok=True)
        # also point the global _dir-derived log path to tmp so we don't pollute the repo
        scheduler._logger.handlers.clear()

    def _write_task(self, name, body):
        with open(os.path.join(self.tmpdir, name + ".json"), "w") as f:
            json.dump(body, f)

    def test_no_recipients_yields_unmodified_prompt(self):
        self._write_task("t1", {
            "schedule": "00:00", "repeat": "daily", "enabled": True,
            "prompt": "do thing"
        })
        # need to be past 00:00; stub datetime
        class _DT:
            @classmethod
            def now(cls): import datetime; return datetime.datetime(2026,1,1,1,0)
        with patch.object(scheduler, "datetime", _DT):
            out = scheduler.check()
        self.assertIn("do thing", out)
        self.assertNotIn("自动邮件投递", out)

    def test_recipients_injects_mail_tail(self):
        self._write_task("t2", {
            "schedule": "00:00", "repeat": "daily", "enabled": True,
            "prompt": "do thing",
            "recipients": ["a@x.com", "b@x.com"]
        })
        class _DT:
            @classmethod
            def now(cls): import datetime; return datetime.datetime(2026,1,1,1,0)
        with patch.object(scheduler, "datetime", _DT):
            out = scheduler.check()
        self.assertIn("自动邮件投递", out)
        self.assertIn("a@x.com", out)
        self.assertIn("b@x.com", out)
        self.assertIn("pandoc", out)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test, verify it fails**

Run: `cd /Users/x403/EulerAgent && python -m pytest tests/test_scheduler_inject.py -v`
Expected: `test_recipients_injects_mail_tail` fails because no injection code exists.

- [ ] **Step 3: Modify `reflect/scheduler.py`**

In `check()`, find the return block at the end (around L125-129). Replace it with:

```python
        # 触发
        _logger.info(f'TRIGGER {tid} (repeat={repeat}, schedule={sched}, '
                     f'last_run={last})')
        ts = now.strftime('%Y-%m-%d_%H%M')
        rpt = os.path.join(DONE, f'{ts}_{tid}.md')
        prompt = task.get('prompt', '')
        recipients = task.get('recipients', [])
        mail_tail = ''
        if recipients:
            mail_tail = (f'\n\n[自动邮件投递]\n'
                         f'收件人：{", ".join(recipients)}\n'
                         f'完成后请执行：\n'
                         f'  1. 写报告到 {rpt}\n'
                         f'  2. 用 code_run 跑：pandoc {rpt} -o {rpt}.docx\n'
                         f'  3. 调 do_send_email，to={recipients}, subject="..."，'
                         f'body="..."，attachments=[{rpt}.docx]\n'
                         f'  4. 邮件发送状态由 do_send_email 自动写入报告头')
        return (f'[定时任务] {tid}\n'
                f'[报告路径] {rpt}\n\n'
                f'先读 scheduled_task_sop 了解执行流程，然后执行以下任务：\n\n'
                f'{prompt}{mail_tail}\n\n'
                f'完成后将执行报告写入 {rpt}。')
```

- [ ] **Step 4: Run test, verify it passes**

Run: `cd /Users/x403/EulerAgent && python -m pytest tests/test_scheduler_inject.py -v`
Expected: 2 tests pass.

- [ ] **Step 5: Commit**

```bash
git add reflect/scheduler.py tests/test_scheduler_inject.py
git commit -m "feat(scheduler): inject recipients + pandoc + send_email into task prompt"
```

---

### Task 7: Update `memory/daily_report_sop.md` with Word section

**Files:**
- Modify: `memory/daily_report_sop.md` (append section)

- [ ] **Step 1: Read end of SOP**

Run: `tail -5 /Users/x403/EulerAgent/memory/daily_report_sop.md`
Use the actual last line as anchor for the Edit below.

- [ ] **Step 2: Append the "Word 附件输出" section**

Edit `/Users/x403/EulerAgent/memory/daily_report_sop.md` — find the last meaningful line and add after it (preserving the "字数控制" section if it ends with that line):

```markdown

## Word 附件输出（可选）
- 用 pandoc 转：`pandoc <md_path> -o <docx_path>`
- 推荐参数：`pandoc <md> -o <docx> --reference-doc=default.docx`（如有企业模板）
- 中文表格/列表：pandoc 默认支持；如乱码确认 locale 是 UTF-8
- docx 大小上限：Gmail 25MB / QQ 50MB / 企业邮箱自定；超过则拆条或改云链接
```

- [ ] **Step 3: Commit**

```bash
git add memory/daily_report_sop.md
git commit -m "docs(sop): add Word 附件输出 section for pandoc integration"
```

---

### Task 8: Update `README.md` and `CONTRIBUTING.md` with ekey setup line

**Files:**
- Modify: `README.md`
- Modify: `CONTRIBUTING.md`

- [ ] **Step 1: Find a good insertion point in README**

Run: `grep -n "ekey\|install\|setup\|首次" /Users/x403/EulerAgent/README.md | head -5`
Use the first install/setup section as anchor.

- [ ] **Step 2: Add the ekey setup line**

In `/Users/x403/EulerAgent/README.md`, after the install/clone section, add (with Edit using the existing block as anchor):

```markdown

## 首次配置

```bash
cp ekey.template.py ekey.py
# 编辑 ekey.py，填入真实 LLM API key 和 EMAIL_SMTP 凭证
```
```

- [ ] **Step 3: Same for CONTRIBUTING.md**

Run: `grep -n "ekey\|setup\|首次" /Users/x403/EulerAgent/CONTRIBUTING.md | head -5`
Add a similar 2-3 line block in the setup section, if one exists. If CONTRIBUTING.md has no setup section, add it after the first H2 heading.

- [ ] **Step 4: Commit**

```bash
git add README.md CONTRIBUTING.md
git commit -m "docs: document cp ekey.template.py ekey.py setup step"
```

---

## PR-3 (optional): example task JSON

### Task 9: Add sample task JSON

**Files:**
- Create: `sche_tasks/example_daily_email.json`

- [ ] **Step 1: Create the file**

Write to `/Users/x403/EulerAgent/sche_tasks/example_daily_email.json`:

```json
{
  "schedule": "08:00",
  "repeat": "weekday",
  "enabled": false,
  "prompt": "按 memory/daily_report_sop.md 的指引，抓取 ../sche_tasks/monitor_urls.json 中的 URL 列表，生成今日多类别资讯日报。",
  "max_delay_hours": 4,
  "recipients": ["REPLACE_WITH_REAL_EMAIL@example.com"]
}
```

> `enabled: false` 是有意：示例不应被 scheduler 误触发。真实使用前改 `enabled: true` 并替换占位邮箱。

- [ ] **Step 2: Verify it parses**

Run: `python -c "import json; d=json.load(open('/Users/x403/EulerAgent/sche_tasks/example_daily_email.json')); print(d['recipients'])"`
Expected: prints `['REPLACE_WITH_REAL_EMAIL@example.com']`.

- [ ] **Step 3: Commit**

```bash
git add sche_tasks/example_daily_email.json
git commit -m "docs(scheduler): add example task JSON for daily email workflow"
```

---

## Self-Review

**1. Spec coverage** — check each spec section against tasks:
- §1.1 复用资产 (scheduler/done path) — Task 6 uses real `rpt` path, ✓
- §1.2 现状缺口 (no email code) — Task 4 adds it, ✓
- §1.3 外部依赖 (pandoc) — Task 6 prompt injects pandoc, Task 7 SOP explains, ✓
- §3.1 ekey.template.py — Task 1, ✓
- §3.2 do_send_email — Task 4, ✓
- §3.3 tools_schema — Task 5, ✓
- §3.4 task JSON recipients — Task 6 reads it, Task 9 example, ✓
- §3.5 prompt injection — Task 6, ✓
- §3.6 SOP word section — Task 7, ✓
- §4 错误处理 (KeyError, retry, file not found) — Task 4 tests cover all, ✓
- §5 测试 — Task 4 unit + Task 6 scheduler test, ✓
- §6 ekey cleanup — Tasks 1-3, ✓
- §7 变更清单 — all files covered above, ✓
- §8 实施顺序 — PR-1 (Tasks 1-3), PR-2 (Tasks 4-8), PR-3 (Task 9), ✓
- §9 风险 — addressed via retry (Task 4), pandoc SOP (Task 7), ✓
- §10 范围之外 — none of the 7 explicit non-goals appear in tasks, ✓

**2. Placeholder scan** — searched the plan for "TBD", "TODO", "implement later", "fill in details": none found. All code blocks are complete. No "similar to Task N" cross-references.

**3. Type consistency** —
- `do_send_email(self, args, response)` consistent across Task 4 test + implementation
- `EKEY.get("EMAIL_SMTP")` consistent in Task 4
- `args.get("to"/"subject"/"body"/"attachments")` consistent
- `StepOutcome(data, next_prompt, should_exit)` consistent
- `attachments=[{rpt}.docx]` in scheduler prompt + `args.get("attachments")` in tool — path string format consistent

**No issues found — plan is ready.**

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-10-daily-report-email-delivery.md`.

Two execution options:

1. **Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration
2. **Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
