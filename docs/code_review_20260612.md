# EulerAgent 整体 Review（2026-06-12）

依据 CONTRIBUTING.md 五原则评审，范围：全仓，排除 `temp/`、`frontends/`。
通读文件：core/（agentmain、agent_loop、ea、llm/ 全部 7 模块、llmcore shim）、TMWebDriver.py、simphtml.py、hub.pyw、launch.pyw、ea_cli/、reflect/、plugins/、tests/、assets/scripts/、pyproject.toml。

---

## 一、总评

核心约 3K 行实现了完整的 agent loop + 多协议 LLM 适配 + 浏览器/文件/代码工具 + 分层记忆，密度很高，整体符合 CONTRIBUTING 的"compact / self-documenting"基调。**`core/llm/` 的分层拆分是全仓最佳实践**：单向依赖（config/models/history → wire → codec → sessions → clients）、模型特判收敛到 `models.py` 一张表、契约测试锁住最脆的 codec 层——这正是"change points converging at boundaries"的范例。

主要短板集中在三处：
1. **边缘正确性**：几个无人值守路径上的崩溃点和语义反转的代码；
2. **热路径性能**：web 工具链每次动作的全页快照 + 模块热重载；
3. **入口层冗余**：三个 launcher、复制粘贴的 bot 启动块、失效的交叉引用——与"More features → less code"相悖。

---

## 二、按 CONTRIBUTING 五原则逐条评估

| 原则 | 评分 | 依据 |
|---|---|---|
| Self-documenting, minimal comments | ✅ 良 | 注释克制且多为"约束说明"（如 history.py 的 atomic write 注释）；少数例外见 §六 |
| Compact and visually uniform | ✅ 良 | 单行 if、密集风格全仓一致；`configure_ekey.py`（1284 行，全仓最大文件）是离群点 |
| Small change radius | ⚠️ 中 | llm/ 分层好；但 `codec.__all__` 导出私有名 + `import *`、三份 history 状态、`sys.path` 注入式导入拓扑，改动需多点同步 |
| More features → less code | ⚠️ 中 | models.py 能力表是正例；launch.pyw 六段复制的 bot 块、三个 launcher 入口、simphtml 死代码是反例 |
| Let it crash by failure radius | ⚠️ 中 | wire/codec 的错误降级设计得当（错误变文本块流回 LLM 自愈）；但 simphtml 多处裸 `except:`，而 `--task` 模式反而该 catch 的没 catch（见 P1-1） |

---

## 三、正确性问题（按优先级）

### P1 — 建议尽快修

1. **`--task` 无人值守模式可被 `queue.Empty` 整体击穿**
   `core/agentmain.py:229` `dq.get(timeout=300)` 未捕获超时异常。display_queue 仅在产出 >30 字符增量时入队，一个静默执行超过 5 分钟的 `code_run`（timeout 参数由 LLM 自定，可远大于 300s）会让整个后台任务进程直接崩溃退出。建议：捕获 `queue.Empty` 后继续等待（以 handler 仍在运行为条件），或把 300s 改为与最大工具 timeout 联动。

2. **中间结果写盘概率与注释意图相反**
   `core/agentmain.py:230` `if 'next' in item and random.random() < 0.95:  # 概率写一次中间结果`——实际 95% 的增量都触发整文件重写，"降频"形同虚设。意图若是抽样降 IO，阈值应在 0.05 一侧；若是"几乎总是写"，注释应改。二者必有一处是错的。

3. **`ToolClient.total_cd_tokens` 累加的是累积缓冲区而非单条消息**
   `core/llm/clients.py:96` 循环内 `user += ...; self.total_cd_tokens += len(user) // 3`——每条消息加的是"到目前为止整个 prompt 的长度"，计数超线性膨胀，过早越过 9000 阈值触发 `last_tools = ''`，导致工具 schema 被不必要地全量重发（直接浪费 token，与该机制的省 token 目的相反）。应累加 `len(本条消息)`。

4. **`compress_history_tags._cd` 是进程级共享计数器**
   `core/llm/history.py:12` 用函数属性做冷却计数，所有 session、所有线程共享。多会话并发（task + reflect + 前端同进程）时 interval 语义互相干扰：A 会话的调用会消耗 B 会话的压缩冷却。应挂到 session 实例上（`trim_messages_history` 已持有 sess）。

5. **TMWebDriver 静默切换到"任意活跃标签页"执行 JS**
   `TMWebDriver.py:210-216` 请求的 session 不活跃时，自动改用 `alive_sessions[0]` 并继续执行。对一个能点按钮、提交表单的 agent 来说，"在错误的页面上执行了带副作用的 JS"比"报错"危害大得多。建议：默认改为抛错返回 tab 列表让 LLM 重选；自动切换至多用于只读操作。

6. **空 LLM 配置报错为 `ZeroDivisionError`**
   `core/agentmain.py:85` `self.llm_no % len(self.llmclients)`——ekey 中无一条有效配置时，用户看到的是除零异常而非"没有可用的 LLM 配置"。首次配置体验路径，值得一条明确报错。

### P2 — 低危 / 择机

7. **`agent_loop.py:76` `next_prompts = set()`** — 多工具调用时 `'\n'.join(set)` 顺序不确定，同一轮的 anchor prompt 拼接结果不可复现（影响 prompt cache 命中与调试复现）。改 list + 去重即可。
8. **`EulerAgent.lock` 创建后从未使用**（agentmain.py:56）— 死状态，删除或启用。
9. **`stream=False` 时按字符 yield** — `BaseSession.ask` 非流式返回 str，`ToolClient.chat` 对其 `for chunk in gen` 逐字符迭代，每个字符穿透整条生成器链（loop → run → display_queue）。非流式配置下一次响应产生数千次无谓调度。
10. **`hub.pyw` EXCLUDES 与 `ea_cli` 引用漂移**（见 §六），以及 `TMWebDriver.__init__` 中探测端口的 socket 未关闭（句柄泄漏，量小）。

---

## 四、性能

按热路径影响排序：

1. **`execute_js_rich` 的页面变化监控是全量快照 ×2 + 全页 diff**（simphtml.py:820-873）
   每次 `web_execute_js`（默认 no_monitor=False）：执行前取全量 HTML（maxchars=9999999）→ 执行后再取一次 → BeautifulSoup 解析两棵全树、对每个元素算签名做 diff，外加固定 `time.sleep(1)`。重页面（长列表、SPA）下单次工具调用增加数秒和数十 MB 内存。这是 agent 操作浏览器的最高频路径。建议：
   - diff 基线截断到合理上限（如 200K 字符），超出即降级为"变化监控不可用"；
   - 把 `time.sleep(1)` 改为短轮询 DOM ready；
   - 评估默认值反转——读类脚本占多数时，让 LLM 显式要 monitor 比默认全量监控更省。

2. **`web_scan` 每次调用 `importlib.reload(simphtml)`**（core/ea.py:160）
   热路径上每次重新编译执行 873 行模块，且 reload 会重置模块全局态。这是开发期热改的便利性泄漏进了运行时。建议：用 mtime 守卫（仿 `reload_ekeys` 的做法）或环境变量开关，仅文件变化时 reload。

3. **`trim_messages_history` 修剪循环 O(n²)**（history.py:70-73）
   while 循环每 pop 一条就对全 history 重新 `json.dumps` 求 cost。context_win 70K（deepseek 行）× 3 字符预算下，一次深度修剪要做几十次全量序列化。维护增量长度即可线性化。

4. **`code_run` 固定 1s 轮询**（ea.py:90）— 每次代码执行最少 ~1s 尾延迟；高频小命令（agent 常态）累积可观。0.05s 起步的指数退避轮询可把常见路径降到接近零成本，不增加行数。

5. **设计内但值得标注**：ToolClient 文本协议每轮重发全 history（靠 trim 兜底）；`_get_anchor_prompt` 每轮注入最近 30 条 history——两者是该架构的核心 token 成本，建议在 README/CLAUDE.md 标注量级预期，避免后续贡献者误判为 bug。

---

## 五、安全

P0 加固（audit log、危险命令拦截、`_SESSION_SETTABLE` 白名单、ekey 入 .gitignore）已落地，以下是残余项：

1. **CDP link token 熵不足且非加密随机**
   `core/agentmain.py:37` `hex(random.randint(0, 99999999))[2:8]` ≈ 27 bit、`random` 模块可预测。默认 127.0.0.1 下风险有限，但 `TMWebDriver(host=...)` 一旦绑 0.0.0.0，`/link` 即等于"弱 token 保护的远程任意 JS 执行"。一行改成 `secrets.token_hex(16)`，零成本消除。

2. **`TMWebDriver.jump` 的 URL 字符串注入**
   `TMWebDriver.py:298` f-string 拼 `window.location.href='{url}'`，URL 含引号即逸出为任意 JS。传 `json.dumps(url)` 即可。

3. **NativeClaudeSession 伪装 Claude Code 客户端**
   sessions.py:131-148 伪造 `claude-cli` user-agent、beta headers、合成 device_id/session_id。这是对上游 API 的客户端身份伪装，存在 ToS/封号风险，且上游指纹策略一变就静默失效。建议至少在 ekey 模板和文档中向用户明示该风险，并把伪装参数显式列为"用户自担风险"的配置项。

4. **`_danger_match` 是黑名单**（ea.py:12-22）— 设计如此（unattended 模式兜底而非沙箱），但 `python -c`、`os.unlink` 循环、`find -delete` 等等价物均可绕过。建议在 SOP/文档中明确其定位是"减少事故，不是安全边界"，避免误依赖。

---

## 六、引用漂移与冗余（直接违反"小变更半径"与"少代码"）

1. **失效引用**（用户跑到即报错）：
   - `ea_cli/cli.py:56` → `assets/scripts/configure_mykey.py` **不存在**（实为 `configure_ekey.py`）；
   - `ea_cli/cli.py` epilog 示例 `ea web` / `ea pet` 命令未注册；
   - `CLAUDE.md` 写 `frontends/tuiapp_v2.py`，实际是 `tuiapp.py` / `tuiapp3.py`；行数标注已过期（agent_loop 136≠127、ea.py 619≠589）。
2. **三个 launcher 入口重叠**：`hub.pyw`（tkinter 面板）、`launch.pyw`（webview 壳 + bot 拉起）、`ea_cli`（命令分发）各自维护一份"怎么启动 X"的知识，且已经各自漂移（hub 的 EXCLUDES、cli 的 COMMANDS、launch 的 argparse）。建议收敛为一张共享的服务注册表（如 assets 下一个 json/py 表），三个入口都读它——典型的"加一个抽象删三处重复"。
3. **launch.pyw 六段复制粘贴的 bot 启动块**（tg/qq/feishu/wechat/wecom/dingtalk，~36 行）——表驱动循环可压到 ~8 行，净行数显著为负。
4. **simphtml.py:212-218 `return` 后的死代码**（equalmany 分支整段不可达）——要么删，要么把开关上提为参数。
5. **`codec.__all__` 显式导出 `_` 私有名 + clients/sessions `from .codec import *`**：codec 新增/改名一个内部函数需要同步 `__all__`，且 `import *` 让"谁用了什么"不可 grep。建议改为显式 import 列表（与 sessions.py 顶部对 config/wire 的做法一致），净行数约 +3，换 grep 可达性。
6. **`NativeOAISession(NativeClaudeSession)`**：为复用 `ask()` 而继承，OAI 会话携带 `fake_cc_system_prompt`、伪造 device_id 等 Claude 专属状态。继承表达的是 is-a，这里是"借实现"。把 `ask()` 上提到 BaseSession 或中间层，两个 Native 平行继承，变更半径更小。
7. **`configure_ekey.py`（1284 行）硬编码模型目录**（claude-opus-4-7、gpt-5.5 等）——模型迭代周期 < 仓库迭代周期，必然过期。建议目录数据外置为 json（与 `tools_schema.json` 同模式），脚本只留交互逻辑。

---

## 七、状态管理（结构性风险，非 bug）

历史有三个并存载体：`EulerAgent.history`（折叠摘要）、`handler.history_info`（同一 list 的引用）、`llmclient.backend.history`（真实消息）。`next_llm` 在异构 backend 间直接移植 `backend.history`（Claude content-block 格式恰好通用，靠 `_msgs_claude2oai` 兜住），`load_llm_sessions` 用三层 `getattr` 抢救旧 history。当前能跑，但这是全仓"failure 时最难定位责任模块"的区域——任一格式假设破坏（如某 backend 往 history 塞了私有结构）会在切换模型时以离奇方式爆发。建议：
- 给"history 统一为 Claude content-block 格式"这条隐性契约补一个契约测试（仿 test_codec 的做法，测 next_llm 跨 ToolClient/NativeToolClient 移植）；
- 长期可考虑 history 归 EulerAgent 持有、session 无状态化，但这是大手术，先用测试锁住契约即可。

---

## 八、测试

现有 6 个契约测试（codec、loop protocol、sse、trim、model_caps、parse_tool_text）选点准确——全部押在协议转换这个最脆层上，符合项目哲学。缺口按价值排序：

1. **MixinSession failover**（clients.py:168-197）：重试/spring-back/部分失败切换是手写状态机，无任何测试，且是"模型挂了能不能自愈"的关键路径；
2. **`_fold_earlier` / `_get_anchor_prompt`**（ea.py）：工作记忆折叠逻辑，错了表现为"agent 失忆"，极难从现象定位；
3. **`_handle_slash_cmd` 白名单**：P0 安全机制本身应有回归测试；
4. **wire `_stream_with_retry`** 的 streamed 后不重试语义。

---

## 九、优化建议汇总（按投入产出排序）

| # | 建议 | 优先级 | 预期净行数 |
|---|---|---|---|
| 1 | `--task` 模式捕获 `queue.Empty`，修复后台任务崩溃 | P1 | +2 |
| 2 | 修正 `random() < 0.95` 的写盘概率/注释反转 | P1 | 0 |
| 3 | `total_cd_tokens` 改为累加单条消息长度 | P1 | 0 |
| 4 | `_cd` 计数器从函数属性移到 session 实例 | P1 | 0 |
| 5 | TMWebDriver 不活跃 session 改为报错而非静默换 tab | P1 | ~0 |
| 6 | CDP token 改 `secrets.token_hex`；`jump()` URL 用 json.dumps | P1 | 0 |
| 7 | `web_scan` 的 simphtml reload 加 mtime 守卫 | P2 | +3 |
| 8 | execute_js_rich diff 基线设上限 + sleep 改轮询 | P2 | ~0 |
| 9 | trim 循环维护增量 cost，消 O(n²) | P2 | ~0 |
| 10 | launch.pyw bot 块表驱动；删 simphtml 死代码 | P2 | **-30 以上** |
| 11 | 三 launcher 收敛共享服务注册表；修 ea_cli 失效引用 | P2 | 负 |
| 12 | 空 LLM 配置给出明确报错 | P2 | +2 |
| 13 | 补 MixinSession / anchor prompt / slash 白名单测试 | P2 | +（测试不计入核心） |
| 14 | NativeOAISession 解除对 NativeClaudeSession 的继承 | P3 | ~0 |
| 15 | configure_ekey 模型目录外置 json；同步 CLAUDE.md 行数/文件名 | P3 | 负 |
| 16 | 文档标注：danger 黑名单非安全边界、CC 伪装的 ToS 风险、文本协议 token 成本量级 | P3 | +几行文档 |

合计：P1 六项均为局部小修（变更半径 ≤1 文件），P2 中 #10/#11 可实现明显的净负行数，符合"refactor 净行数为负"的 PR 检查项。

---

## 十、落地状态（2026-06-12 同日实施）

- **已完成**：#1–#10、#12、#13（新增 test_mixin_failover / test_handler_guards，36 用例全绿）、#16（ea.py 黑名单与 sessions.py 伪装风险各一行标注）、#15 的文档部分（CLAUDE.md 行数/tuiapp 引用、ea_cli 失效引用）。另顺手：删除未使用的 `EulerAgent.lock`、TMWebDriver 探测 socket 改 with 关闭、simphtml 裸 `except:` 收窄为 `except Exception`。整体净 **-20 行**（+82/-102）。
- **未实施（建议开 Issue 讨论后单独 PR）**：#8 的 DOM-ready 轮询（已做 diff 体量上限与 no_monitor 免 sleep，轮询部分收益/风险比存疑）；#11 的三 launcher 注册表收敛（跨 3 入口的结构调整，属 non-trivial）；#14 NativeOAISession 解继承；#15 configure_ekey 模型目录外置。
