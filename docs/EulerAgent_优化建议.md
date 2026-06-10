# EulerAgent 优化建议

> 日期：2026-06-08
> 依据：完整阅读 `core/`、`llmcore.py`、`simphtml.py`、`TMWebDriver.py`、`reflect/`、`frontends/`、`ea_cli/` 后，结合 [CONTRIBUTING.md](CONTRIBUTING.md) 五项原则与项目核心价值（**信息密度最大化 / 省 token / AI 可反复阅读 / 极简内核**）。
> 说明：本文只给方向、理由与改动半径评估，**不直接写实现代码**。

---

## 评判标尺（来自 CONTRIBUTING + 核心价值）

每条建议都对照以下标尺，标注它服务于哪一条：

| 代号 | 原则 | 含义 |
|---|---|---|
| **D1** | 自文档化、最小注释 | 代码即文档，需要整段注释才能解释 = 该重写 |
| **D2** | 紧凑、视觉统一 | 更少行、一致行宽、无冗余 |
| **D3** | 小改动半径 | 改 A 不波及 B/C/D |
| **D4** | 更多功能→更少代码 | 好抽象让代码库收缩 |
| **D5** | 按失败半径崩溃 | 关键错误大声失败，琐碎静默，**禁止 blanket try-catch** |
| **V1** | 信息密度 / 省 token | 内核与 prompt 的每个 token 都要有价值 |
| **V2** | AI 可读性 | 文件会被 AI 读上千次，结构与文档必须可信 |

---

## P0 — 与核心原则直接冲突，建议优先处理

### 1. 裸 `except:` 泛滥，违反 D5「No blanket try-catch」

**证据**：`core/` 四个文件中 `except` 共 69 处，其中**裸 `except:` 27 处、`except Exception` 21 处**。例如 [llmcore.py](core/llmcore.py) 的 `tryparse`、`_parse_*_sse` 解析循环、`MixinSession`，以及 [agentmain.py:62](core/agentmain.py) `try: oldhistory = self.llmclient.backend.history / except: oldhistory = None`。

**问题**：这是与 CONTRIBUTING 明文冲突最严重的一点。裸 `except` 会吞掉 `KeyboardInterrupt`、`SystemExit`、拼写错误导致的 `NameError/AttributeError`，让"关键错误大声失败"失效——一个本应崩溃定位的 bug 会被静默成"返回默认值"，最终在远处以诡异行为暴露，违背 D5「on failure can I quickly locate the responsible module」。

**建议方向**：
- 做一次「except 审计」，把每处分类为三类：(a) **预期的、可恢复的**（如 JSON 解析失败回退）→ 收窄到具体异常类型（`json.JSONDecodeError`、`requests.Timeout`）；(b) **真正不关心的清理**（如 `print` 失败、关流）→ 保留但注明；(c) **不该吞的**（搬运历史、属性访问）→ 改为显式判断（`hasattr`/`getattr` 带默认）而非 try/except。
- 这本身就是一次「净行数为零、风险显著下降」的理想 refactor，完全符合 PR Checklist。

**改动半径**：中。逐文件、逐处独立修改，互不影响，适合拆成多个小 PR。

---

### 2. `llmcore.py` 职责过载（1032 行），违反 D3 小改动半径 + D4 好抽象

**证据**：单文件承担了 4 类会话（Claude/LLM/NativeClaude/NativeOAI）× 2 套协议（messages / chat_completions / responses）× 流式与非流式 × 工具文本协议解析 × 历史裁剪 × 缓存标记 × 多模型 fallback。`_parse_openai_sse` 一个函数内 `responses` 与 `chat_completions` 两套分支并存（[llmcore.py:199-291](core/llmcore.py)）。

**问题**：这是全仓回归风险最集中的文件。改任何一家 API 的解析、加一个新模型特化（如已有的 deepseek/kimi/minimax 散落特判），都要在这块"无边界大文件"里穿行，正是 D3 想避免的"改 A 波及 B/C/D"。也违反 D4——它是"功能多导致代码膨胀"的反例。

**建议方向**（注意：拆分本身不能为拆而拆，要让净复杂度下降）：
- 按**清晰边界**切分为三层概念，而非按行数硬切：① **wire 层**（HTTP/SSE 收发与重试，已有 `_stream_with_retry` 是好抽象的雏形）；② **协议编解码层**（claude↔oai↔responses 的 messages/tools 互转 + SSE 事件→统一 content_block）；③ **会话/策略层**（BaseSession、Mixin、ToolClient/NativeToolClient）。
- 把散落的模型特判（`'deepseek' in model`、`'kimi'/'minimax'`、`gpt-5/o1` 的 max_tokens 字段名、temperature 钳制）收敛为**一张模型能力表/特征字典**，新增模型 = 加一行表项，而不是再加一处 `if`。这正是 D4「加功能=加实现不改旧逻辑」。

**改动半径**：大，且高风险（无测试护航）。**前置条件是先有契约测试**（见 P1.6），否则拆分本身会引入回归。建议作为中期目标，不要一次性大重构。

---

### 3. 文档与代码不一致，违反 V2「文件会被 AI 读上千次，必须可信」

**证据**：
- [CLAUDE.md](CLAUDE.md) 架构图与「Agent Initialization」描述 `core/handlers/`（BaseHandler 扩展点），但**该目录实际不存在**（`BaseHandler` 在 `core/agent_loop.py` 内）。
- CLAUDE.md「Import Notes」示例 `from core.ga import ...`——仓库里没有 `ga` 模块（应为 `ea`）。
- [README.md:250](README.md) 把 agent loop 链接成根目录 `agent_loop.py`，实际在 `core/agent_loop.py`。

**问题**：本项目的核心卖点是"代码/文档会被 AI 反复读取"。一旦 AI（包括 EulerAgent 自己做自举时）读到不存在的路径或模块名，要么浪费 token 去验证，要么直接产生幻觉去 `import core.ga`，与 V1/V2 根本目标背道而驰。文档不准对这个项目的伤害**比普通项目大一个量级**。

**建议方向**：把 CLAUDE.md / README 的所有路径、模块名、目录引用做一次「事实核对」，删除 `core/handlers/` 的虚构描述（或反过来：若确实想保留 handler 扩展点，就建目录并落地一个最小示例，让文档变真）。改 docstring 链接为 `core/` 实际路径。

**改动半径**：极小，纯文档，零代码风险，收益直接命中核心价值。**建议立刻做。**

---

## P1 — 工程健壮性

### 4. 容错解析层脆弱且难以观测（D5 + V2）

**证据**：[llmcore.py](core/llmcore.py) 的 `_parse_mixed_response`、`_parse_text_tool_calls`、`tryparse` 用大量正则与字符串切割（`weaktoolstr.strip('><')`、`json_str[:json_str.rfind('}')+1]`、`re.split(r'(?<=\})(?=\{)')`）兜底模型不规范输出。

**问题**：这是支撑"高兼容性"卖点的关键，但也是最容易在新模型上静默崩坏的地方——解析失败时往往退化为 `bad_json` 或空 tool_calls，难以归因到底是模型输出变了还是正则不对。

**建议方向**：
- 不必重写，但应**收紧失败信号**：当文本协议解析彻底失败时，保留原始片段到日志（已有 `_write_llm_log` 可复用），并让失败「响一点」——目前部分路径静默 `except: pass`（如 `_parse_text_tool_calls` 内），与 D5 冲突。
- 为这层补**几个最小的解析快照测试**（input 文本 → 期望 tool_calls），把"模型输出格式"作为可回归的契约固定下来。这是少量代码换大量调试时间，符合 D4 精神。

**改动半径**：小，集中在单层函数 + 测试目录。

---

### 5. 安全边界依赖软约束（D5 失败半径 / 实际是「破坏半径」）

**证据**：`do_code_run` 的 `inline_eval` 分支直接 `eval/exec`，命名空间暴露 `handler`、`parent`、完整 `history`（[ea.py:294-303](core/ea.py)）；`code_run` 拥有系统级权限；`web_execute_js` 可执行任意 JS。当前唯一约束是 system prompt 里的"不可逆操作先询问用户"（[sys_prompt.txt](assets/prompts/sys_prompt.txt)）。

**问题**：CONTRIBUTING 的 D5 讲的是"代码失败半径"，但这里是**运行时破坏半径**——在 IM Bot / reflect 自治 / 子 Agent 等无人值守场景下，一条注入的恶意指令即可触达本机全部权限。这与"物理级全能执行者"定位是一体两面，但缺少**分级闸门**。

**建议方向**（不破坏极简）：
- 引入一个**轻量、可选的危险操作确认闸**：在工具层对一组高危模式（`rm -rf`/`format`/凭证文件路径/`os.kill`/批量删除）做正则前置拦截，命中即强制走 `ask_user`。这是"少量代码、明确边界"的护栏，符合 D4。
- 为无人值守模式（reflect / task / bot）提供一个 `--safe` 档，默认禁用 `inline_eval` 与高危命令。把"信任级别"做成一处配置而非散落判断。
- 记忆 SOP 里已有"密钥文件仅引用不读取"的软规则，可把它**下沉为工具层硬校验**（file_read 命中密钥路径直接拒绝），让规则从 prompt 变成代码保证。

**改动半径**：小到中，集中在 `EulerAgentHandler` 工具入口处，不触及循环与适配层。

---

### 6. 缺少契约测试（V2 + 为所有重构兜底）

**证据**：仓库无 `tests/`；`temp/cross_verify.py` 等是任务产物而非测试套件；git 历史仅 2 条提交（打包式发布）。

**问题**：极简哲学常被误读为"不写测试"，但恰恰因为内核小、被 AI 频繁改写（自举），更需要**一层薄薄的安全网**来防止"AI 改完看起来对、实则回归"。没有测试，P0.2 的 `llmcore` 拆分几乎不可能安全进行。

**建议方向**（务必克制，符合 D2「无冗余」）：
- 只为**最稳定的契约**写测试，不追求覆盖率：① `agent_runner_loop` 的生成器协议（喂 mock client，断言 StepOutcome 流转 / no_tool 拦截 / 退出条件）；② `_fix_messages` 的配对修复（这是多轮鲁棒性的命门）；③ 协议互转 `_msgs_claude2oai` / `_to_responses_input` 的往返；④ 解析层快照（见 P1.4）。
- 形态上保持极简：单个 `tests/` 目录、纯 stdlib 或最小依赖、可 `python -m` 直跑，避免引入重测试框架（呼应"No unnecessary dependencies"）。

**改动半径**：纯新增，零现有代码风险，是其他所有重构的前置投资。

---

## P2 — 一致性与可维护性

### 7. 魔法数字散落，违反 D3 + V1（调参要改源码多处）

**证据**：调控"信息密度/省 token"的关键阈值硬编码且分散——`context_win` 默认 30000（[llmcore.py:515](core/llmcore.py)）；工作记忆窗口 `W=30`（[ea.py:535](core/ea.py)）；轮数护栏 `turn%7 / %10 / %75`、`max_turns=80/100/120`（[ea.py](core/ea.py)、[agent_loop.py](core/agent_loop.py)）；工具输出预算 `10000/15000/35000/8000 // _tool_num`（散落 `ea.py` 各 `do_*`）；`compress` 的 `keep_recent`、`max_len`。

**问题**：这些数字**本质上就是本项目的核心竞争力参数**（信息密度的旋钮），却散落在十几处。想做一次"省 token 调优实验"必须改多个文件多个位置，违反 D3，也让 V1 的优化无法系统进行。

**建议方向**：把这组阈值收敛到**一处显式的"密度预算"配置块**（常量集中定义，命名自解释，本身就是 D1 自文档化）。不引入配置框架，就是一个集中常量区。让"调密度"变成改一处。

**改动半径**：小，机械替换，可独立验证，净行数接近零。

---

### 8. 工具 docstring / schema / 实现三处重复维护（D4）

**证据**：每个工具的描述同时存在于 `assets/tools_schema.json`（+ `_cn` / `_en` 变体）、`do_*` 方法 docstring、以及 `ea.py` 顶层函数 docstring。三者需手工保持一致，且有多语言副本。

**问题**：加/改一个工具要同步多份文本，违反 D4「加功能不该让维护点增多」。多语言 schema 副本（`_cn`/`_en`）进一步放大同步成本。

**建议方向**：以 `do_*` 的 docstring 为**单一事实源**，让 schema 的 description 由其生成（构建期或加载期），而非各写一份。语言变体只保留差异部分。目标是"工具定义只写一次"。

**改动半径**：中，涉及 schema 加载路径（[agentmain.py:18-22](core/agentmain.py)），但收益是长期维护点减半。

---

### 9. 前端层重复样板（D4 + D2）

**证据**：14+ 个 `frontends/*.py` 各自重复 `sys.path.insert(parent_dir)`、`script_dir = os.path.dirname(...)` 模板、slash 命令解析、restore/continue 逻辑。`chatapp_common.py` 已抽出一部分（HELP_COMMANDS、RESTORE_GLOBS），但仍不彻底——TG/微信/QQ 等 Bot 仍有大量平行实现。

**问题**：这是仓库 ~24K 行里"功能多导致代码膨胀"最明显的区域，与 D4 相悖。前端虽不属"核心 3K"，但同样会被 AI 阅读与改写。

**建议方向**：把 Bot 前端的共性（消息收发循环、命令分发、流式回显、文件回传）继续上提到 `chatapp_common`，让每个具体 Bot 只剩"平台 SDK 适配"这一薄壳。`sys.path` 注入与 `script_dir` 模板可统一成一个 import helper。

**改动半径**：中，但限定在 `frontends/`，不触内核；可逐个前端渐进收敛。

---

### 10. 模块导入双轨制带来的脆弱性（V2）

**证据**：根级 `llmcore.py`/`TMWebDriver.py` 与 `core/` 版本并存，靠 `sys.path` 两次注入兼容（[agentmain.py:7-8](core/agentmain.py)）；CLAUDE.md 专门有「Import Notes」解释 `from llmcore` 与 `from core.llmcore` 两种写法。

**问题**：需要一段文档解释的导入规则，按 D1 标准属于"需要整段解释 = 该重写"。双轨容易让 AI 改错版本（改了 `core/llmcore` 但运行的是根级副本，或反之）。

**建议方向**：明确**单一事实源**（建议以 `core/` 为准），根级保留为最小转发 shim（或彻底移除并统一 import 路径）。让"哪个是真的"无需文档解释。

**改动半径**：中，需排查所有 import 点；但消除一类隐蔽 bug。

---

## P3 — 锦上添花

### 11. `simphtml` 的 HTML→token 压缩可作为密度优化主战场（V1）

`simphtml.py` 的 `smart_truncate` / `optimize_html_for_tokens` / `get_main_block` 是 web 场景省 token 的核心。当前 `maxchars` 默认 35000，是直接影响成本的旋钮。建议把它纳入 P2.7 的「密度预算」统一管理，并考虑给 `get_html` 增加"按信息密度排序保留"的策略评估（已有 `cutlist`/`find_changed_elements` 基础）。属于长期优化，非紧急。

### 12. 注释语言与风格统一（D1/D2）

代码注释中英混杂（`# just new message, history is kept in *Session`、`# 端口锁：防止重复启动`）。不强求统一语言，但建议：凡需要解释"为什么"的注释保留，凡复述"做什么"的注释删除（那是 D1 要求代码自己表达的）。例如 [agentmain.py:113](core/agentmain.py) `# i know it is dangerous...` 这类属于有价值的 why-注释，应保留。

### 13. `temp/` 内残留任务产物（D2/卫生）

`temp/cross_verify.py`、`temp/*.json` 是历史任务产物，已被 `.gitignore` 部分处理但仍有入库。建议确认 `temp/` 完全纳入 ignore，保持仓库只含"种子"，呼应"~3K 行种子代码"的定位。

---

## 建议的执行顺序（按"风险/收益比"）

```
立即做（零风险、命中核心价值）：
  P0.3 文档事实核对      → V2，纯文档
  P2.7 魔法数字集中      → D3/V1，机械替换
  P3.13 temp 卫生        → 仓库卫生

短期（小半径、高收益）：
  P0.1 except 审计       → D5，逐处独立
  P1.5 危险操作闸门      → 安全，工具层局部
  P1.6 契约测试（薄）    → 为后续重构兜底

中期（需测试护航）：
  P1.4 解析层收紧+快照
  P2.8 工具定义单一源
  P2.9 前端样板收敛
  P2.10 导入双轨统一

长期（大半径、高风险）：
  P0.2 llmcore 分层      → 必须先有 P1.6 测试
  P3.11 simphtml 密度策略
```

---

## 一句话总结

EulerAgent 的代码质量与它宣称的极简哲学**整体高度自洽**，最值得修的不是"写得不好"，而是**几处与自身原则的局部背离**：裸 except 与 D5 冲突、`llmcore.py` 与 D3/D4 冲突、文档失真与 V2 冲突、密度旋钮散落与 V1 冲突。优先从「零风险、直接命中核心价值」的文档核对与常量集中入手，用一层薄契约测试兜底，再逐步收敛适配层——每一步都应让**净行数趋零、改动半径收窄**，这正是 CONTRIBUTING 期望的贡献形态。
