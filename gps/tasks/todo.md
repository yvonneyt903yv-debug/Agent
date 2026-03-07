# Todo

- [x] 基于 `main_translator_prd.md` 确认实施范围：仅改 `src/translator.py`，保持 `translate_article(text)` 外部接口不变。
- [x] 在 `src/translator.py` 实现语义切块、术语抽取、chunk 并发翻译、术语归一化、auto mode 自动降级。
- [x] 保留 `thinking=True`（不调整 `src/deepseek.py`）。
- [x] 运行本地语法与导入级验证，确保无语法错误。
- [x] 回顾改动并更新本文件 Review 区。

- [x] 确认 `siemens.py` 为运行入口，并定位 2026-03-04 无法重跑的根因（固定最近 3 天窗口 + processed 去重）。
- [x] 为 `siemens.py` 增加重跑参数：`--rerun-date`、`--ignore-processed`、`--once`、`--lookback-days`。
- [x] 将 `target_dates` 透传至链接抓取与主处理流程，确保重跑日期可控。
- [x] 在一次性重跑模式下进行语法级验证并给出可执行命令。

# Review

- Date: 2026-03-06
- Scope: main translator 并发分块翻译提速
- Files: `/Users/yvonne/Documents/Agent/src/translator.py`, `/Users/yvonne/Documents/Agent/gps/tasks/main_translator_prd.md`, `/Users/yvonne/Documents/Agent/gps/tasks/todo.md`
- Change path: 新增语义切块、术语抽取、并发分块翻译、失败重试与 auto 降级串行，保持外部接口不变
- Validation: `python3` AST 语法检查通过（`AST_OK`）
- Git commit: not yet
- Sync status: local updated; VPS not yet synced

- Date: 2026-03-07
- Scope: Siemens 3/4 文章重跑支持
- Files: `/Users/yvonne/Documents/Agent/gps/siemens.py`, `/Users/yvonne/Documents/Agent/gps/tasks/todo.md`
- Change path: 增加 CLI 重跑参数；支持按日期覆盖窗口并可忽略 processed 去重；支持 `--once` 单次执行
- Validation: `python3 -m py_compile siemens.py` 通过；`python3 siemens.py --once --rerun-date 2026-03-04` 已跑通并进入微信发布，日志显示 `WeChat publish success`
- Git commit: not yet
- Sync status: local updated; VPS not yet synced
