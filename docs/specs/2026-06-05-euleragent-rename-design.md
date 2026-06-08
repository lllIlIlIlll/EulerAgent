# GenericAgent → EulerAgent 重命名设计文档

## 背景

GenericAgent 项目需要全面更名为 EulerAgent。这是一个纯重命名操作，不涉及架构变更或功能修改。所有代码、文档、配置中的品牌名称统一替换。

## 目标

将所有源码、文档、配置文件中的 GenericAgent 品牌名替换为 EulerAgent，不留旧名残留。

## 非目标（Out of Scope）

| 项目 | 原因 |
|------|------|
| GitHub 仓库 URL（`lsdefine/GenericAgent`） | 仓库保持原名，不做迁移 |
| `GA_LANG` 环境变量 | 改名会破坏已部署用户的 shell 配置 |
| `GenericAgent.exe` 二进制 | 需重新打包桌面端，属于发布流程 |
| `assets/images/bar.jpg` 等 banner 图 | 图片中嵌入了旧品牌名，需重新制作 |
| `fudunkw.cn:9000/files/ga_install.*` | 远程安装脚本需服务端同步部署 |
| `GenericAgent_Technical_Report.pdf` | 论文 PDF，文件名保持原样 |
| `frontends/desktop/static/ga-web.js` 中的 `window.ga`、`selectGaRoot` 等 API 名 | JS↔Rust bridge 的接口契约，改名需同步改 Tauri 端，风险高且不属于品牌展示 |

## 名称映射表

| 旧名称 | 新名称 | 适用场景 |
|--------|--------|---------|
| `GenericAgent` | `EulerAgent` | 类名、显示文本、文档标题 |
| `GeneraticAgent` | `EulerAgent` | 历史拼写错误别名，统一修正 |
| `genericagent` | `euleragent` | 包名、小写 slug |
| `generic_agent` | `euler_agent` | Python 导入路径（如有） |
| `Generic Agent` | `Euler Agent` | 英文文档中的自然语言引用 |
| `ga_cli` / `ga-cli` | `ea_cli` / `ea-cli` | CLI 工具名（目录名、命令名） |
| `ga`（命令别名） | `ea` | `pyproject.toml` entry_point |

### `GA` 缩写的替换边界

`GA` 作为独立缩写的替换**需逐个确认上下文**，不能全局替换。具体规则：

| 替换 | 示例 |
|------|------|
| ✅ 替换 | 注释中指代项目名的 `GA`（如 `"GA dominates token"` → `"EA dominates token"`） |
| ❌ 不替换 | `GA_LANG` 环境变量、`ga-web.js` 文件内的 JS API 名、`GenericAgent_Technical_Report` 中的 `GA` |

## 文件/目录重命名

| 旧路径 | 新路径 |
|--------|--------|
| `ga_cli/` | `ea_cli/` |
| `ga_cli/__init__.py` | `ea_cli/__init__.py` |
| `ga_cli/__main__.py` | `ea_cli/__main__.py` |
| `ga_cli/cli.py` | `ea_cli/cli.py` |
| `ga_cli/ga_cli.cmd` | `ea_cli/ea_cli.cmd` |
| `ga_cli/ga-cli-install.cmd` | `ea_cli/ea-cli-install.cmd` |
| `frontends/genericagent_acp_bridge.py` | `frontends/euleragent_acp_bridge.py` |

## 执行计划

### 第 1 轮 — 文件/目录重命名 + 内部引用修正

```bash
git mv ga_cli ea_cli
git mv frontends/genericagent_acp_bridge.py frontends/euleragent_acp_bridge.py
```

然后修正所有 import 引用：
- `import ga_cli` → `import ea_cli`
- `from ga_cli` → `from ea_cli`
- `import genericagent_acp_bridge` → `import euleragent_acp_bridge`
- `from genericagent_acp_bridge` → `from euleragent_acp_bridge`

### 第 2 轮 — Python 源码文本替换

涉及 27 个 Python 文件（基于扫描结果），主要变更：

- `class GenericAgent` → `class EulerAgent`（[agentmain.py:46](core/agentmain.py#L46)）
- 删除 `GeneraticAgent = GenericAgent` 别名行（[agentmain.py:179](core/agentmain.py#L179)），将 [agentmain.py:204](core/agentmain.py#L204) 的 `GeneraticAgent()` 改为 `EulerAgent()`
- 字符串中的品牌名：`"GenericAgent"` → `"EulerAgent"`（CLI 提示、日志、前端显示）
- 注释/docstring 中的品牌名
- `genericagent` → `euleragent`（包名引用、ACP bridge 等）

### 第 3 轮 — 文档/配置替换

| 文件 | 变更内容 |
|------|---------|
| `pyproject.toml` | `name = "genericagent"` → `"euleragent"`；`ga = "ga_cli.cli:main"` → `ea = "ea_cli.cli:main"`；`packages = ["ga_cli"]` → `["ea_cli"]` |
| `README.md` | 所有 `GenericAgent` / `Generic Agent` → `EulerAgent` / `Euler Agent`；`genericagent` → `euleragent` |
| `CLAUDE.md` | 架构描述中的品牌名 |
| `CONTRIBUTING.md` | 品牌名引用 |
| `docs/*.md` | 安装指南、教程中的品牌名 |
| `docs/report/*.html` | 报告页面中的品牌名 |
| `frontends/desktop/package.json` | `genericagent` → `euleragent` |
| `frontends/desktop/src-tauri/tauri.conf.json` | 标题和标识符 |
| `frontends/desktop/static/*.html` | 页面标题 |
| `memory/review_sop.md` | SOP 文档中的品牌名 |
| `frontends/desktop/static/ga-web.js` | 仅替换注释中的 `GenericAgent` → `EulerAgent`，不动 API 名 |

### 第 4 轮 — 自检 + 验证

```bash
# 确认零残留（排除已知的 out-of-scope 项）
grep -r "GenericAgent\|genericagent\|GeneraticAgent\|ga_cli\|ga-cli" \
  --include="*.py" --include="*.md" --include="*.json" --include="*.toml" \
  --include="*.html" --include="*.txt" --include="*.sh" --include="*.cmd" \
  | grep -v "GA_LANG" \
  | grep -v "GenericAgent_Technical_Report" \
  | grep -v "GenericAgent.exe" \
  | grep -v "ga-web.js"

# 基本导入测试
python -c "from ea_cli.cli import main"
python -c "from core.agentmain import EulerAgent"
```

## 风险与注意事项

1. **`GA_LANG` 混用**：代码中将出现 `EA` 品牌和 `GA_LANG` 环境变量混用。可接受，因为这只是内部变量名。
2. **`GA` 缩写误改**：部分上下文中 `GA` 可能不代表 GenericAgent（如 `GA-Technical-Report`），需逐个确认。
3. **`ga-web.js` API 名**：`window.ga`、`selectGaRoot` 等是 JS↔Rust bridge 的接口契约，暂不改名。仅替换文件内的注释。
4. **单次 diff 规模大**（~303 行变更），建议逐文件 review。

## 关键假设（待验证）

- [ ] `GA_LANG` 环境变量暂不改名，不影响品牌一致性（验证：grep 确认只在内部使用，不面向用户展示）
- [ ] `GeneraticAgent` 别名无外部依赖（验证：grep 确认只在 agentmain.py 内部使用）
- [ ] 所有 Python 文件的 import 路径在重命名后能正确解析（验证：第 4 轮导入测试）
- [ ] `ga-web.js` 中的 API 名不需要改名（验证：确认 `window.ga` 被 Tauri Rust 端引用，改动需同步）

## 开放问题

- 无
