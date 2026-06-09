# 多源URL日报整编 SOP (daily_report_sop)

适用：用户提供 100+ 个监控 URL 列表，要求生成 24h 内多类别（矿产/医药/气候等）新闻日报的场景。

## 关键前置
- 监控源数量大（200+ 量级）→ 优先 Python `requests` 30 线程并行，不要走浏览器
- 时效性硬约束（仅 N-1 ~ N 日窗口）→ 严格按报道日期过滤，窗口外条目进"附录跟踪中事项"
- 涉外涉华优先 + 严禁编造 → 失补时宁缺勿滥，标注"窗口外"

## 典型坑（多次重试核心）
1. **raw HTML 主页日期提取严重不准** — header/footer/copyright/favicon 里的年份污染；只
...[Truncated]...
头中
- `deta
...[Truncated]...
eport_urls.json`、`fetch_results.json`、`raw_html/`、`detail_fetched.json`）

## 已知失败/降级站点
- JS 重度：WMO、UNFCCC、IISD、IRENA、PRB、Codex、PRIC → raw HTML 仅 nav+版权，需浏览器或 RSS
- 握手/超时：USDA、Saudi Aramco、ENE-METI、DCCEEW、Met Éireann → 跳过或换代理
- 编码异常：部分中文站点 GBK 未声明 → requests 用 `resp.apparent_encoding` 或 UTF-8 容错

## 字数控制
- "4500-6000 字"通常指中文字符数（不算 markdown 符号），用 `re.findall(r'[\u4e00-\u9fff]', text)` 精确统计
- 不足时优先扩充"趋势分析"与"信号价值"（每段可加 100-200 字深度），不要凑数式复制条目
