# EulerAgent 安全性 / 稳定性 / 健壮性 加固方案

> 范围：`core/`、`TMWebDriver.py`、`launch.pyw`、`reflect/`、`assets/plugins/`、`plugins/`（排除 `frontends/`、`temp/`）。
> 原则：**不削减"系统级无约束控制"这一核心价值**，只在 *信任边界* 与 *失败可控性* 上加固。
> 每项均附证据（`文件:行`）、改动半径、与 CONTRIBUTING 原则的关系。本文件是方案，不含成片实现代码。

---

## 0. 结论速览

代码抽象收敛良好（`model_caps` 表、`core/llm/` 单向分层、`StepOutcome` 协议），风格统一。真实风险集中在两类：

1. **不可信输入驱动无约束能力**（注入链 / 凭证劫持 / 凭证泄露）—— 这是该产品形态的固有代价，靠"确认闸门 + 审计 + 白名单"缓解，而非砍能力。
2. **后台多线程共享状态无锁** —— 纯工程问题，改动小、收益大，应最先做。

优先级总表：

| 状态 | 级别 | 编号 | 项 | 改动半径 |
|---|---|---|---|---|
| ✅ | P0 | F1 | `.gitignore` 补 `ekey.json` —— 当前明文凭证可被误提交 | 1 行 |
| ✅ | P0 | F2 | TMWebDriver 共享 dict 加锁 | 单文件局部 |
| ✅ | P0 | F3 | `/session.k=v` 字段白名单 | 单函数 |
| ✅ | P1 | F4 | `code_run` 审计日志 + 无人值守高危闸门 | 新增一个边界点 |
| ✅ | P1 | F5 | 裸 `except:` 收敛为精确异常类型 | 分散但每处 1 行 |
| ⬜ | P2 | F6 | TMWebDriver `/link` + agent_bbs 收紧网络暴露面 | 局部 |
| ⬜ | P2 | F7 | inline_eval 去全局 `os.chdir`；loop 内 `json.loads` 容错 | 两处局部 |
| ⬜ | P3 | F8 | 日志路径双轨统一；`file_access_stats` 并发安全；DEBUG 噪声 | 杂项 |

> F1–F5 已实现（commit `1a2af2f` + `b7160cf`）。下文各节"方案"为原始设计；F4/F5 的**实际落地说明**见对应章节末尾。

---

## P0 — 必做，改动小且零争议

### F1. `.gitignore` 未覆盖 `ekey.json`（凭证泄露）

**证据**
- [core/llm/config.py:22](../core/llm/config.py) — 无 `ekey.py` 时 fallback 到 `core/ekey.json` 存放全部明文 apikey。
- `.gitignore` 仅含 `ekey.py` / `mykey.py`，**无 `ekey.json`**（已核实 `git ls-files` 未跟踪，但一次 `git add .` 就会进仓库）。

**方案**
- `.gitignore` 增加 `ekey.json` 与 `**/ekey.json`（fallback 路径在 `core/` 下，无目录前缀的规则也能匹配，但显式更稳妥）。
- 顺带核对：`temp/`、`memory/file_access_stats.json` 已忽略 ✅；`assets/tmwd_cdp_bridge/config.js`（含随机 TID）建议一并忽略，它是运行时生成物（[agentmain.py:33-38](../core/agentmain.py)）。

**改动半径**：纯 `.gitignore`，零代码风险。

---

### F2. TMWebDriver 共享字典多线程无锁（长跑崩溃首因）

**证据** —— `sessions` / `results` / `acks` 被 WS 线程、多个 HTTP 长轮询线程、agent 主线程并发增删，全程无锁：
- 迭代中删除：`clean_sessions` 的 `del self.sessions[sid]`（[TMWebDriver.py:113-118](../TMWebDriver.py)）与 `execute_js` 里 `for session in self.sessions.values()`（[TMWebDriver.py:197](../TMWebDriver.py)）、`get_all_sessions` 的推导式（[TMWebDriver.py:253](../TMWebDriver.py)）并发 → 典型 `RuntimeError: dictionary changed size during iteration`。
- `results[...] = ...`（WS 与 HTTP 两条回调路径，[TMWebDriver.py:80](../TMWebDriver.py) / [147](../TMWebDriver.py)）与 `results.pop(exec_id)`（[TMWebDriver.py:237](../TMWebDriver.py)）竞争。
- `_register_client` / `_unregister_client`（[TMWebDriver.py:164-181](../TMWebDriver.py)）与上述读路径竞争。

**方案**
- 在 `TMWebDriver.__init__` 增一把 `self._lock = threading.RLock()`。
- 用它包住对 `sessions` / `results` / `acks` 的**所有增、删、整体迭代**；`execute_js` 的轮询 `while exec_id not in self.results` 循环体里只在取/弹结果的瞬间持锁，不要整圈持锁（否则阻塞回调写入）。
- 所有"遍历后修改"统一改成先 `list(self.sessions.items())` 快照再处理（项目里部分位置已这么写，目标是全一致）。

**与原则的关系**：失败可定位、小change radius——锁只收敛在 driver 内部，不外溢。
**改动半径**：单文件 `TMWebDriver.py`，纯内部状态保护。

---

### F3. `/session.k=v` 任意属性注入（凭证可被劫持）

**证据**
- [core/agentmain.py:113-126](../core/agentmain.py) `_handle_slash_cmd` 对 `self.llmclient.backend` 执行 `setattr(k, v)`，`k`/`v` 全来自用户输入；`v` 还会先尝试读 `temp/<v>` 文件内容。注释自承 "i know it is dangerous"。
- 任何能投递文本的前端（telegram / bbs / wechat 等 bot）都能借此把 `api_key`、`api_base` 改成攻击者端点，**静默窃取后续全部对话与凭证**。

**方案**
- 维护一个**显式白名单**集合，仅允许 ekey 模板里已公开的可调参数：
  `reasoning_effort, service_tier, thinking_type, thinking_budget_tokens, temperature, max_tokens, max_retries, stream`（依据 [core/llm/sessions.py:64-74](../core/llm/sessions.py) 的 `BaseSession.__init__` 字段）。
- `k` 不在白名单 → 返回 `❌ 不允许设置 {k}`，不 `setattr`。
- 保留"读 `temp/` 文件填值"能力即可，但仅对白名单 key 生效。

**改动半径**：单函数 `_handle_slash_cmd`，新增一个常量集合 + 一个 `if`。

---

## P1 — 应做，对抗根本性风险

### F4. 提示注入 → RCE 链：确认闸门 + 审计日志

**背景（架构级，不是单行 bug）** —— 循环把**不可信内容**喂进 LLM，LLM 输出又能直接触发本机任意执行：
- 不可信来源：`web_scan` / `web_execute_js` 的网页正文（[ea.py:114](../core/ea.py) / [164](../core/ea.py)）、`file_read` 任意文件、`agent_bbs` 他方帖子、`_intervene`/`_keyinfo` 注入文件（[ea.py:572-575](../core/ea.py)）。
- 能力出口：`code_run` 的子进程执行（[ea.py:281](../core/ea.py)）、`inline_eval` 的 `eval/exec`（[ea.py:300-301](../core/ea.py)）、`file_write/patch`、`web_execute_js`。
- 放大器：`launch.pyw` idle_monitor 在用户离开 30 分钟后**自动注入任务**（[launch.pyw:68-82](../launch.pyw)），使该链可在无人值守时触发。

现有的 `turn%7/75` DANGER 提示、plan 模式"验证拦截"（[ea.py:466-469](../core/ea.py)）都是"提示 LLM 自律"，对注入攻击无效。**核心价值要求保留任意执行能力，所以方案不是禁止，而是加可观测性 + 对不可逆操作加闸门。**

**方案**
1. **审计日志（先做，成本最低）**：在 `code_run` 入口（[ea.py:12](../core/ea.py)）落一条结构化记录到独立文件（如 `temp/audit/code_run.log`，与 `model_responses` 分离）：时间、turn、code_type、code 全文、cwd。事后可追溯"哪一轮、什么来源触发了什么执行"。
2. **不可逆/外向操作闸门**：对命中危险模式的 shell/python（`rm -rf`、`mkfs`、`:(){`、`curl|sh`、向外网 POST 大量本地数据、`git push --force`、发邮件 `do_send_email` 等）增加一个**独立于 LLM 的确认点**——复用现有 `ask_user`（[ea.py:94](../core/ea.py)）的 INTERRUPT 机制即可，不需新协议。默认在交互模式弹确认；在 `--task`/`--reflect` 无人值守模式下，默认拒绝并记录（可由 ekey/配置显式放行）。
3. **来源染色（可选增强）**：在 `turn_end_callback`（[ea.py:547](../core/ea.py)）标记"本轮读过 web/bbs 等外部来源"，若紧接着的下一轮就 `code_run`，在审计日志里标 `HIGH_RISK`。

**与原则的关系**：能力不减，但"失败/越权可快速定位"——正是 CONTRIBUTING 第 4 条。
**改动半径**：审计日志是单点新增；闸门集中在 `do_code_run` 一处判断。

> **实际落地（commit `b7160cf`）**：
> - 审计：`_audit_code_run` 把每次执行（含 inline_eval）写入 `temp/audit/code_run.log`，含时间/turn/类型/`HIGH_RISK:<原因>` 或 `NORMAL`/cwd/代码全文。
> - 闸门：`_danger_match` 用高确信正则（`rm -rf`、`mkfs`/`dd`、fork bomb、`shutdown`、`git push --force`、`curl|sh`、`shutil.rmtree`）。命中且 `parent.unattended`（`--task`/`--reflect` 置位）时**直接返回 error 拒绝执行**，提示 LLM 改用 `ask_user`；交互模式照常执行但留审计。
> - **为何不用 `ask_user` 弹确认**：`ask_user` 会 `should_exit` 中断循环等待人答，回答后新一轮仍会再次命中闸门 → 确认续接需要"放行态"语义，改动半径大且要前端配合。无人值守硬拦截在不在场时同样生效，更符合"独立于 LLM 的策略"目标，且零死循环风险。

---

### F5. blanket `except Exception` 与 CONTRIBUTING 冲突

**证据** —— CONTRIBUTING 明确"No blanket try-catch；关键错误响亮地崩"，但多处把所有异常吞成 error 字符串，使**程序员 bug 被降级成普通工具失败**，LLM 反复重试同一根因（现靠 `turn%7 禁止无效重试` 打补丁，治标）：
- [ea.py:142](../core/ea.py) `web_scan`、[ea.py:173](../core/ea.py) `web_execute_js`、[ea.py:401](../core/ea.py) `do_file_write`、[plugins/hooks.py:17-25](../plugins/hooks.py) `trigger`、`reflect/scheduler.py` 多处 `except:`。

**方案** —— 区分两类，不要一刀切：
- **预期失败**（网络 timeout、文件不存在、HTTP 4xx/5xx）→ 维持现状，返回 error 给 LLM 决策。
- **程序员错误**（`TypeError`/`KeyError`/`AttributeError`）→ 至少用 `format_error`（[ea.py:145](../core/ea.py)，已能输出 `文件:行:函数`）落 **ERROR 级日志**，或在 verbose/dev 模式直接抛。
- 收敛 `reflect/scheduler.py:59`、`:117` 等**裸 `except:`** 为具体异常类型（已有几处做了 `except (ValueError, IndexError)`，目标是全一致）。

**改动半径**：分散但每处 1-2 行；不改控制流，只改"吞 vs 抛 + 日志级别"。

> **实际落地（commit `b7160cf`）**：本次只收敛了**裸 `except:`**（会吞 `KeyboardInterrupt`/`SystemExit` 的真 bug）三处 → 精确类型：`langfuse_tracing.py`(JSONDecodeError)、`reflect/scheduler.py`(ValueError)、`launch.pyw`(AttributeError,OSError)。`web_scan`/`web_execute_js`/`do_file_write` 等 `except Exception` 评估后**保留**——它们处在工具边界，把失败作为 error 返回给 LLM 决策是合理的"预期失败"，且已用 `format_error` 输出 `文件:行` 便于定位。如需进一步区分"程序员错误响亮崩"，建议作为独立 backlog 推进，避免一次性扩大改动半径。

---

## P2 — 收紧暴露面 / 去隐患

### F6. TMWebDriver `/link` 无鉴权 + agent_bbs 绑 0.0.0.0

**证据**
- `/link`（[TMWebDriver.py:85-102](../TMWebDriver.py)）收到 JSON 即 `execute_js` 任意浏览器 JS，无 token；虽绑 `127.0.0.1`，本机任意进程可命中。
- `agent_bbs` 硬编码 `host="0.0.0.0"`（[assets/plugins/agent_bbs.py:215](../assets/plugins/agent_bbs.py)），暴露到整个 LAN（虽有 `ApiKeyMiddleware`，但 host 不该默认全网开放）。

**方案**
- `/link`：启动时生成随机 token（与 CDP bridge 已有的随机 `__ljq_xxxx` 机制一致，见 [agentmain.py:37](../core/agentmain.py)），`/link` 请求头或 body 校验该 token；`is_remote` 探测端可从同一文件读取。
- agent_bbs：`host` 改为读 env，默认 `127.0.0.1`，需要 LAN 时显式 `BBS_HOST=0.0.0.0`；文档启动注释同步。

**改动半径**：`/link` 一处校验；agent_bbs 一行 + 文档。

---

### F7. inline_eval 全局 `os.chdir`；loop 内 `json.loads` 隐式不变量

**证据**
- [ea.py:298-303](../core/ea.py) inline_eval `os.chdir(cwd)` 改的是**整个进程** cwd，而 TMWebDriver 的 HTTP/WS 线程同时在跑、可能基于相对路径写文件。窗口虽短，仍是隐患。
- [agent_loop.py:70](../core/agent_loop.py) 对 native tool_calls 直接 `json.loads(tc.function.arguments)` 无 try；当前所有路径都经 `MockToolCall`（内部 `json.dumps`）保证合法，但这是**隐式不变量**——未来新增透传原始 arguments 的 session 就会无声崩整轮。

**方案**
- inline_eval：用显式 `cwd` 上下文而非全局 `chdir`（如把代码包进一个临时切目录的子进程，或在 `exec` 的 namespace 里注入 `os.getcwd` 返回值），消除进程级副作用。
- loop：把 `json.loads(...)` 换成 codec 已有的 `tryparse`（[codec.py:388](../core/llm/codec.py)），与项目"容忍脏 JSON"的整体风格一致。

**改动半径**：两处各 1-3 行。

---

## P3 — 清理项（低优先，顺手做）

### F8. 杂项

- **日志双轨统一**：`wire._write_llm_log` 默认 `model_responses_{pid}.txt`（[wire.py:35](../core/llm/wire.py)）vs `agentmain` 设的 `model_responses_{time%1e6}.txt`（[agentmain.py:56](../core/agentmain.py)）。`/resume`（[agentmain.py:124](../core/agentmain.py)）与 L4 归档按"最近修改文件尾部"找会话，两套命名混用可能拼接不完整会话。→ 统一为单一命名来源。
- **`file_access_stats.json` 并发写覆盖**：`log_memory_access`（[ea.py:154-162](../core/ea.py)）read-modify-write，`--task` 子进程 + `--reflect` 调度进程并发时互相覆盖。→ 改 append-only 行日志或加文件锁（已 gitignore，仅影响统计可信度）。
- **DEBUG 噪声**：`BaseSession.ask` 的 `if len(content_blocks) > 1: print([DEBUG ...])`（[sessions.py:98](../core/llm/sessions.py)）在正常多块响应时刷屏。→ 降级或加开关。

---

## 落地顺序建议

1. **F1 + F2 + F3**（P0）：一次提交即可显著降风险——补 gitignore、driver 加锁、session 白名单，三者互不耦合。
2. **F5**（P1）：随后逐文件按 failure-radius 调整 except，配合 `format_error` 落 ERROR 日志。
3. **F4**（P1）：先上审计日志（纯新增、无副作用），再迭代危险操作闸门。
4. **F6 / F7 / F8**：按需穿插。

> 每项都满足 CONTRIBUTING 的自检：可局部修改、change radius 收敛在边界、失败可快速定位、净增行数小（F1 为负，F2/F3 个位数行，F4 审计为单点新增）。
