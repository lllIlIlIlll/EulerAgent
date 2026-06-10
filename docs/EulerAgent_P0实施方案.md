# EulerAgent P0 实施方案：except 审计整改 + llmcore.py 拆分

> 日期：2026-06-08
> 范围：`core/agent_loop.py`、`core/agentmain.py`、`core/ea.py`、`core/llmcore.py`
> 原则锚点：CONTRIBUTING D3（小改动半径）、D5（按失败半径崩溃 / 禁止 blanket try-catch）、PR Checklist（净行数趋零、无新依赖）
> 形态：方案文档。含少量 before/after 模式示意与模块骨架，**不提交成品实现**。

---

# Part A — except 审计与整改

## A.1 整改决策树（每一处 except 必须归入四类之一）

```
这个 except 捕获的是什么？
│
├─ 生成器协议 (StopIteration) ........... [K] 保留，是惯用法，不动
│
├─ 已经是具体异常类型 .................... [K] 保留（可选：补一句 why 注释）
│
└─ 是裸 except: 或宽 except Exception
     │
     ├─ try 块是"预期会失败、且有明确恢复值"
     │   （JSON 解析、int 转换、读可选文件、解析 header）
     │        → [N] 收窄到该操作真正会抛的具体异常类型
     │
     ├─ try 块是"纯展示/清理，失败无所谓"
     │   （print 到终端、写 banner、关流、best-effort 增强）
     │        → [N] 收窄到 OSError（IO 类）并保留 pass，行尾注明意图
     │
     ├─ try 块是"不该失败的正常逻辑"
     │   （属性访问、历史搬运、re-raise）
     │        → [C] 改为显式判断 (hasattr/getattr)；
     │           re-raise 用 `except Exception as e: ... raise ... from e`，绝不裸吞
     │
     └─ try 块是"任务/网络/插件/用户脚本的边界"
         （单个工具调用、单个任务、reflect 用户脚本、HTTP 请求）
              → [B] 宽捕获是合理的"失败半径围栏"，**保留 except Exception**，
                 但必须 (1) 带 as e (2) 打印或返回可定位信息（含来源）
```

图例：**[K]** 保持 · **[N]** 收窄异常类型 · **[C]** 改写为显式判断/正确 re-raise · **[B]** 合理边界、仅补全可观测性

---

## A.2 完整审计表（全部 68 处，行号已对齐当前 HEAD）

### `core/agent_loop.py` —— 全部合格，**不改**

| 行 | 现状 | 判定 | 说明 |
|---|---|---|---|
| 5 | `except ImportError` | K | 可选 hook 插件，已具体 |
| 35 | `except StopIteration` | K | `exhaust` 协议 |
| 88 | `except StopIteration` | K | dispatch 返回值协议 |

> 核心循环本身完全符合 D5，可作为其他文件整改的「样板风格」。

### `core/agentmain.py`

| 行 | 现状 | 判定 | 目标动作 |
|---|---|---|---|
| 14 | `except Exception: pass`（插件发现） | B | 插件加载失败应可见、但不该阻断启动：保留宽捕获，改 `except Exception as e:` 打 `[WARN] plugin load failed: {e}`，不要静默 |
| 38 | `except Exception as e: print WARN`（CDP config） | B | 已合格；可收窄到 `OSError` |
| 63 | `except: oldhistory = None`（取 backend.history） | **C** | 改显式：`getattr(getattr(self,'llmclient',None),'backend',None)` 链，或 `hasattr` 判断。裸 except 在此会吞 AttributeError 拼写错误 |
| 70 | `except: pass`（resolve_client 单配置） | N | 一个 key 配错用户必须知道：收窄到可预期错误并 `print [WARN] skip config {k}: {e}` |
| 77 | `except Exception as e: print ERROR`（Mixin 初始化） | B | 已合格 |
| 88 | `except: raise Exception('BAD Mixin config...')` | **C** | 裸 except 重抛会丢原始 traceback：改 `except Exception as e: raise RuntimeError(...) from e` |
| 121 | `except (json.JSONDecodeError, ValueError)` | K | 已具体（slash 命令解析） |
| 170 | `except Exception as e:`（run 主循环任务边界） | B | **合理的失败半径围栏**：保留宽捕获（单任务崩溃不应拖垮 agent 线程）；建议日志加 `traceback` 而非仅 `format_error` |
| 244/247/257/265 | reflect 各 `except Exception as e: print` | B | reflect 加载**用户脚本**，宽捕获正当；已打印，合格。可统一前缀便于定位 |
| 269 | `except Exception: pass`（import readline） | N | 收窄 `ImportError` |
| 273 | `except Exception: model='?'` | B | 显示降级，合格 |
| 278 | `except Exception: pass`（写 banner） | N | 收窄 `OSError`，注明"纯显示" |
| 288 | `except KeyboardInterrupt` | K | 已具体 |

### `core/ea.py`

| 行 | 现状 | 判定 | 目标动作 |
|---|---|---|---|
| 45 | `except UnicodeDecodeError` | K | 已具体（gbk 回退） |
| 48 | `except: pass`（stream_reader 内 print） | N | 收窄 `OSError`，注明"终端输出可丢" |
| 49 | `except: pass`（stream_reader 线程体） | N | 进程结束时读管道会抛异常：收窄到 `(OSError, ValueError)` 并行尾注明 |
| 87 | `except Exception as e:`（code_run 顶层） | B | 工具边界，合格 |
| 142 | `except Exception as e:`（web_scan） | B | 工具边界，合格 |
| 159 | `except: stats={}`（读 stats json） | N | 收窄 `(FileNotFoundError, json.JSONDecodeError)` |
| 173 | `except Exception as e: return error`（web_execute_js） | B | 工具边界，合格 |
| 202 | `except Exception as e: return error`（file_patch） | B | 工具边界，合格 |
| 210 | `except (PermissionError, OSError)` | K | 已具体 |
| 238 | `except FileNotFoundError` | K | 已具体 |
| 247 | `except Exception: pass`（模糊推荐计算） | N | best-effort 增强：收窄到计算真正会抛的类型，注明"推荐失败不影响主结果" |
| 249 | `except Exception as e: return Error`（file_read 兜底） | B | 工具边界，合格 |
| 289 | `except: timeout=60` | N | 收窄 `(ValueError, TypeError)` |
| 301 | `except SyntaxError: exec` | K | 已具体（eval→exec 回退） |
| 302 | `except Exception as e: result=Error`（inline_eval） | B | 执行用户代码，宽捕获正当，合格 |
| 348 | `except: 保存失败提示` | N | 收窄 `OSError` |
| 351 | `except: pass`（print） | N | 收窄 `OSError` |
| 364 | `except ValueError as e:` | K | 已具体（引用展开） |
| 401 | `except Exception as e:`（file_write 边界） | B | 工具边界，合格 |
| 433 | `except: return None`（plan 完成度检查） | N | 收窄 `(OSError, re.error)` |
| 544 | `except: pass`（print anchor） | N | 收窄 `OSError` |
| 589 | `except FileNotFoundError: pass` | K | 已具体 |

### `core/llmcore.py`

| 行 | 现状 | 判定 | 目标动作 |
|---|---|---|---|
| 11 | `except ImportError: pass` | K | 已具体 |
| 84 | `except OSError`（safeprint） | K | 已具体 |
| 127 | `except Exception as e:`（SSE JSON 解析，已 print+continue） | B | 边界合格 |
| 157/177 | `except: input={"_raw":...}`（tool json） | N | 收窄 `json.JSONDecodeError` |
| 189/195 | `except`（_try_parse_tool_args 切分） | N | 收窄 `json.JSONDecodeError` |
| 214/263 | `except: continue`（SSE 行） | N | 收窄 `json.JSONDecodeError` |
| 320/335 | `except: args={"_raw":...}`（function_call args） | N | 收窄 `json.JSONDecodeError` |
| 356 | `except: ra=None`（retry-after float） | N | 收窄 `(TypeError, ValueError)` |
| 369 | `except: body=""`（r.text） | N | 收窄 `Exception`→具体，或保留 B 并注明 |
| 375 | `except StopIteration` | K | 协议 |
| 378 | `except (requests.Timeout, requests.ConnectionError)` | K | 已具体 |
| 385 | `except Exception as e:`（流式顶层兜底） | B | 网络边界，合格 |
| 562/685/941/1013 | `except StopIteration` | K | 协议 |
| 837 | `except json.JSONDecodeError` | K | 已具体 |
| 840 | `except: pass`（紧跟 837 的二次兜底） | **C** | 这里吞掉 JSONDecodeError 之外的一切（含 KeyError/TypeError 逻辑 bug）：明确写出预期类型，其余让它崩 |
| 856/864 | `except: pass`（text tool calls 解析） | N | 收窄 `json.JSONDecodeError` |
| 888/891/893 | `except: pass`（tryparse 三段） | N | 收窄 `json.JSONDecodeError` |

### A.2.1 统计汇总

| 判定 | 数量 | 含义 |
|---|---|---|
| **K** 保持 | 20 | 协议 / 已具体，0 改动 |
| **N** 收窄异常 | 27 | 机械替换，最大批量（llmcore 占 15） |
| **B** 合理边界 | 18 | 保留宽捕获，仅补 `as e` + 可观测信息 |
| **C** 改写/正确重抛 | 3 | agentmain:63、agentmain:88、llmcore:840 — 风险最高，最该先修 |

> 归类规则：「目标动作仍保留 `except Exception`」记 B，「收窄到具体类型」记 N。边界项（agentmain:70、ea:49、ea:247、llmcore:369）介于两者之间，本表一律按"能收窄就收窄"归 N；若反向归 B，则 N/B 各浮动至多 4 处，不影响批次划分与结论。
>
> 关键结论：真正"危险"的只有 **3 处 [C]**（吞 AttributeError、丢 traceback、吞逻辑 bug）。它们体量极小但收益最高，应作为整改第一刀。

---

## A.3 收窄的标准写法（before / after 示意）

**[N] 收窄**——以 `tryparse`（llmcore:888）为例，意图本就是"逐级尝试解析 JSON"：
```
# before
try: return json.loads(json_str)
except: pass
# after
try: return json.loads(json_str)
except json.JSONDecodeError: pass   # 预期失败，进入下一种修复
```

**[C] 显式判断**——agentmain:63 历史搬运：
```
# before
try: oldhistory = self.llmclient.backend.history
except: oldhistory = None
# after（无 try：本就是"有则取、无则 None"的判断）
oldhistory = getattr(getattr(self, 'llmclient', None), 'backend', None)
oldhistory = getattr(oldhistory, 'history', None)
```

**[C] 正确重抛**——agentmain:88：
```
# before
except: raise Exception('[ERROR] BAD Mixin config: Check your ekey.py')
# after
except Exception as e:
    raise RuntimeError('[ERROR] BAD Mixin config: Check your ekey.py') from e
```

**[B] 补可观测性**——agentmain:14 插件加载：
```
# before
except Exception: pass
# after
except Exception as e: print(f'[WARN] plugin discover failed: {e}')
```

---

## A.4 分批 PR 计划（每批独立、可单独回滚、净行数≈0）

| 批次 | 内容 | 处数 | 风险 | 验证 |
|---|---|---|---|---|
| **PR-A1** | 仅 3 处 [C]（agentmain:63/88、llmcore:840） | 3 | 中 | 跑 A.5 烟囱测试 + 手动触发一次正常对话、一次坏 ekey |
| **PR-A2** | llmcore 全部 [N]（15 处解析类，统一收 `json.JSONDecodeError` 等） | 15 | 低 | 解析快照测试（见 Part B 测试网） |
| **PR-A3** | ea.py 全部 [N]（9 处 IO/转换类） | 9 | 低 | 工具级手测：超时参数、坏 stats 文件、plan 检查 |
| **PR-A4** | agentmain [N]（3）+ agentmain 全部 [B]（9）补 `as e`/日志 | 12 | 低 | reflect/CLI 启动冒烟 |
| **PR-A5** | ea + llmcore 的 [B]（7+2）纯补 `as e`/统一日志前缀 | 9 | 低 | 工具/网络边界各触发一次失败，确认可定位 |

> 处数随 A.2.1 修正后上调（原表按 47 处的旧统计低估了 [B]）。A4/A5 按文件聚合拆分，避免单 PR 横跨 4 文件、改动半径过大。
>
> 顺序原则：**先修真危险的 [C]，再做机械的 [N]，最后补 [B] 的可观测性。** 每个 PR 都满足"净行数趋零"（多数是同行替换）。

## A.5 验证基线（无测试时的最小手动烟囱）

整改前先固化「当前行为」作为对照：
1. CLI 正常对话一轮（文本协议模型 + native 模型各一次）。
2. 故意写错一个 ekey 配置 → 期望明确报错而非静默。
3. reflect 跑一个会抛异常的脚本 → 期望日志可定位。
4. 喂一个非法 JSON 工具调用 → 期望降级为 `bad_json` 且日志留痕。

整改后逐项复跑，行为应**完全一致**（[N]/[B] 不改变可恢复路径，[C] 只是让本应崩的更早崩）。

---

# Part B — llmcore.py 拆分

## B.1 现状职责盘点（1032 行，单文件混装 7 类关注点）

| 关注点 | 代表符号 | 约行数 |
|---|---|---|
| 配置加载 | `_load_ekeys` `reload_ekeys` `__getattr__` `safeprint` | 80 |
| 历史裁剪 | `compress_history_tags` `_sanitize_leading_user_msg` `trim_messages_history` | 70 |
| HTTP/SSE wire | `_stream_with_retry` `auto_make_url` `_record_usage` `_write_llm_log` | 120 |
| 协议编解码 | `_parse_claude_*` `_parse_openai_*` `_msgs_claude2oai` `_to_responses_input` `_fix_messages` `_drop_unsigned_thinking` `_ensure_thinking_blocks` `openai_tools_to_claude` `_prepare_oai_tools` `_try_parse_tool_args` `tryparse` `_stamp_oai_cache_markers` | 400 |
| 会话类 | `BaseSession` `ClaudeSession` `LLMSession` `NativeClaudeSession` `NativeOAISession` `_openai_stream` | 250 |
| 客户端/工具协议 | `ToolClient` `NativeToolClient` `MixinSession` `Mock*` `_parse_text_tool_calls` `_ensure_text_block` `THINKING_PROMPT_*` | 280 |
| 解析入口 | `resolve_session` `resolve_client` `fast_ask` | 20 |

**核心痛点**：改任一家 API（如新增模型特化）要在这块无边界大文件里穿行；模型特判（deepseek/kimi/minimax/gpt-5）散落在 `BaseSession.__init__`、`_openai_stream`、`make_messages` 等多处 —— 违反 D3，且是 D4 的反例。

## B.2 目标结构（包 `core/llm/`，按概念层切，非按行数切）

```
core/llm/
├── __init__.py     # facade：re-export 全部公开符号，对外 import 零变化
├── config.py       # ekey 加载 + safeprint
├── history.py      # 裁剪/压缩
├── wire.py         # _stream_with_retry / auto_make_url / _record_usage / _write_llm_log
├── codec.py        # 所有协议编解码 + 消息修复 + tryparse 系列
├── models.py       # ★新增：模型能力表（替代散落特判）
├── sessions.py     # BaseSession + 4 个 Session + 请求构造
└── clients.py      # ToolClient / NativeToolClient / MixinSession / Mock* / resolve_* / fast_ask
```

依赖方向（单向，无环）：
```
config ← (无依赖)
history ← (无依赖)
wire    ← config(safeprint)
codec   ← (无依赖，纯函数)
models  ← (无依赖，纯数据)
sessions← wire, codec, history, models, config
clients ← sessions, codec, config
__init__← 全部
```

### B.2.1 关键设计：`models.py` 模型能力表（落地 D4）

把现有散落特判收敛成**一行一模型**的特征字典，新增模型 = 加一行，不再改逻辑：

| 现状散落特判（举例） | 收敛后表项字段 |
|---|---|
| `'deepseek' in model` → context_win/cut_interval/keep_rate/保留 thinking | `context_win, cut_interval, trim_keep_rate, keep_thinking` |
| `'kimi'/'moonshot'` → temperature=1 | `temperature_override` |
| `'minimax'` → temp 钳到 (0,1] | `temperature_clamp` |
| `gpt-5/o1/o3` → `max_completion_tokens` 字段名 | `max_tokens_field` |

`BaseSession`/`_openai_stream` 改为查表，特判逻辑从 N 处收敛到 1 处。**这是拆分能带来净复杂度下降的核心理由**——否则只是搬运。

## B.3 前置条件：测试网（必须先于任何拆分落地）

无测试时拆 1032 行 = 盲拆。先建**纯 mock、零真实 API、stdlib 可跑**的契约测试（呼应"无新依赖"）：

| 测试文件 | 锁定的契约 | 为什么是命门 |
|---|---|---|
| `test_codec_roundtrip` | `_msgs_claude2oai` / `_to_responses_input` 对一组标准 history 的输出快照 | 协议互转是拆分最易碎处 |
| `test_fix_messages` | tool_use/tool_result 配对修复、角色交替、孤儿降级 | 多轮鲁棒性命门 |
| `test_parse_sse` | 喂固定 SSE 字节流，断言 yield 文本 + 返回 content_blocks | 锁定四家解析行为 |
| `test_parse_tool_text` | 各种畸形 `<tool_use>` 文本 → 期望 tool_calls | 兼容性卖点的回归网 |
| `test_trim_history` | 超预算 history → 裁剪后规模与首条为 user | 上下文管理正确性 |
| `test_loop_protocol` | mock client 喂入 → `agent_runner_loop` 的 StepOutcome 流转/no_tool/退出 | 跨 Part 的总安全网 |

测试通过 = 拆分前的"行为基线"。形态：单 `tests/` 目录、`python -m unittest` 直跑、不引入 pytest 等重依赖。

## B.4 迁移策略：Strangler（绞杀者）分阶段，每阶段行为零变化

核心手法：**先建 facade 让外部 import 不变，再从内部一层层抽，每抽一层跑全测试。** 改动半径被锁在包内。

```
阶段 0  建测试网（B.3），全绿 = 基线确立
        ────────────────────────────────────────
阶段 1  纯搬运：把现 llmcore.py 原样移成 core/llm/_legacy.py
        写 core/llm/__init__.py：from ._legacy import *（+ 显式 __all__）
        core/llmcore.py 退化为一行 shim：from core.llm import *（见 B.6，保持 sys.path 下 `from llmcore import` 不变）
        ✅ 验证：全测试绿 + A.5 烟囱。此阶段零逻辑改动，纯文件移动
        ────────────────────────────────────────
阶段 2  抽叶子（无依赖层）：config.py / history.py / codec.py / models.py
        从 _legacy 移出定义，_legacy 改为 from .codec import * 等
        每抽一个文件 → 跑全测试 → 提一个 PR（净行数≈0）
        ★ models.py 落地时同步把散落特判改为查表（唯一有逻辑变化的步骤，
          单独 PR、单独验证不同模型路径）
        ────────────────────────────────────────
阶段 3  抽 wire.py（依赖 config）
        ────────────────────────────────────────
阶段 4  抽 sessions.py（依赖 wire/codec/history/models）
        ────────────────────────────────────────
阶段 5  抽 clients.py（依赖 sessions/codec）
        ────────────────────────────────────────
阶段 6  删除 _legacy.py（此时应已空或仅剩 re-export）
        __init__.py 改为从各真实模块显式 re-export
        ✅ 终验：全测试绿 + 四种 client（Claude/LLM/Native×2）各跑一轮真实对话
```

每个阶段都是**可独立合并、可独立回滚**的 PR，符合 PR Checklist「净行数趋零」。

## B.5 facade（`__init__.py`）必须 re-export 的对外符号

以现有外部 import 为准（[agentmain.py:10](core/agentmain.py)）：
```
reload_ekeys, LLMSession, ToolClient, ClaudeSession, MixinSession,
NativeToolClient, NativeClaudeSession, NativeOAISession, resolve_client
```
加上其他被引用的：`resolve_session`、`fast_ask`、`BaseSession`、`compress_history_tags` 等。
**`__all__` 必须显式列全**，否则 `from llmcore import *` 漏符号会在运行时才暴露。这是阶段 1 的验证重点。

## B.6 一并消除 `sys.path` 注入与文档偏差（P2.10）

**事实更正**：根级 `llmcore.py` 实际并不存在（git 历史中从未有过），唯一文件是 `core/llmcore.py`；[agentmain.py:10](core/agentmain.py) 能 `from llmcore import` 全靠把 `core/` 注入 `sys.path`。因此这里不是"双轨"，而是 **import 路径魔法 + CLAUDE.md 描述与实际不符**（CLAUDE.md 称"根级 llmcore.py"为兼容层，属虚构）。

拆分时定调：**`core/llm/` 为唯一事实源**；为不破坏现有 `from llmcore import`，保留一行 shim `core/llmcore.py`：`from core.llm import *`。同步修正 CLAUDE.md 里"根级 llmcore.py"的描述——那段需要整段解释的 import 规则正是 D1 该消除的对象。

### B.6.1 CLAUDE.md 待修正项（B.6 落地时一并处理）

真实机制：[agentmain.py:7](core/agentmain.py) 用 `sys.path.insert(0, <core 目录>)` 把 **`core/` 本身**置为顶层搜索路径，故 `from llmcore import` / `from agent_loop import` / `from ea import` 解析到的都是 `core/*.py`。全仓**没有任何** `from core.llmcore import` 的调用。据此，CLAUDE.md 以下描述均与代码不符：

| CLAUDE.md 位置 | 现写法 | 问题 | 落地动作 |
|---|---|---|---|
| 架构图 第 32 行 | `llmcore.py … (root level …)` | llmcore.py 在 `core/`，非 root | 移到 `core/` 节点下；或注明根级仅留 shim |
| Import Notes 第 101-102 行 | `# From root level files: from llmcore import …` | 根级无此文件 | 删除该节 |
| Import Notes 第 105-106 行 | `from core.llmcore import …` | 代码从不这样 import | 改为说明"`core/` 经 sys.path.insert 成为顶层，故 `from llmcore import`" |

> 注：架构图 第 33 行 `TMWebDriver.py (root level)` 属实（根级确有该文件），不在修正之列。整段 Import Notes 删改后净行数为负——正是 D1「需要整段文档解释＝该消除」的落地。

## B.7 风险与回滚

| 风险 | 缓解 |
|---|---|
| 循环 import | B.2 已定义单向依赖；codec/models 设计为零内部依赖的纯函数/纯数据 |
| `from ._legacy import *` 漏私有符号 | 阶段 1 用显式 `__all__`；私有 `_xxx` 跨模块引用改为显式 import |
| 模型特判查表后行为漂移 | models.py 单独 PR，对每个已知模型（deepseek/kimi/minimax/gpt-5/claude）跑一轮对照 |
| 无测试覆盖的隐藏路径 | 阶段 0 测试网为硬门槛；终验补四 client 真实对话 |
| 拆分中途需暂停 | Strangler 每阶段自洽可发布，可在任意阶段停住而不留半成品 |

回滚：任一 PR 独立 revert 即可，因 facade 保证对外接口在整个过程中恒定。

---

## 总结

- **Part A**：68 处 except 已逐一定级（行号对齐当前 HEAD），真正危险仅 3 处 [C]，27 处 [N] 为机械收窄，18 处 [B] 是合理边界只需补可观测性。分 5 个净行数≈0、按文件聚合的 PR，先修 [C]。
- **Part B**：llmcore.py 拆分**必须测试先行**，用 Strangler 分 6 阶段、每阶段行为零变化、改动半径锁在包内；拆分真正的价值不在"分文件"，而在 `models.py` 把散落模型特判收敛成一张表（落地 D4），并顺手消除 `sys.path` 注入与 CLAUDE.md 文档偏差（落地 D1/D3）。
- 两部分都严守 CONTRIBUTING：**净行数趋零、无新依赖、改动可独立定位与回滚**。
