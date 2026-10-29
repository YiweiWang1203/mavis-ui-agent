# T-LG-002 LangGraph 有界反馈回路工程交付

日期：2026-10-29。状态：**本机工程实现完成，待导师在原 Ubuntu UV 独立复核后统一启动**。本轮未调用真实模型，不计 0/20 效果轮。

## 1. 实际实现边界

实现的是显式 UI 子图，不声称 coordinator、planner、ASR 或额外 reviewer 已运行。子图节点为：

`ui_architect → coordinate_quality_gate → supervisor → (ui_architect 最多一次 | render | stop)`

- 首次与修正均使用专用 target-layout prompt；prompt SHA256：`e3326c89cdede10fdb051edad34b0bc89de4214938f26cda059027156677bcfd`。
- local code 注入可信 frame/target provenance；模型不生成真实 frame hash。
- 质量门控只验证数值、坐标空间、viewport ID、来源引用和修正不变量。`release_gate.status=coordinate_contract_passed` 明确不是语义、peer 冲突、页面或用户验收通过。
- baseline 与 candidate 共享同一次新观察和首次架构原答；baseline 发现失败后停止，candidate 只有在已知可修硬错误时允许一次架构修正。
- 首答通过时两臂直接渲染，不强制修正、不注错、不重跑挑优。
- 未知错误、解析失败、对象库存变化、未授权字段变化或第二次仍错均停止，不交付旧 HTML。

## 2. 职责歧义修复

`src/prompts/ui_architect_target_layout_v1.md` 明确：

- 视觉 bbox 只属于照片观察，不是目标 CSS 坐标。
- 架构模型负责每个输出元素的 target viewport placement。
- local code 只验证和编译，不用照片框覆盖、不乘 viewport、不夹限、不猜变换。
- caller 提供 frame/target 身份；架构响应提供 `viewport_px`、viewport ID、derivation 和来源引用。

`generate_target_layout_attempt` 将该 prompt 真正放入请求 system message，固定 8192 output token、600秒、零 SDK 自动重试。解析失败保留首次 raw response 和解析位置；provider 异常由子图记录异常类型，不被旧 `generate_ui_state` 通用 except 吞成无诊断字符串。

按提前复核要求，本轮 runner 的视觉调用保持旧实验真实入口：`extract_ui_layout(image, user_context=intent)` 与 legacy 默认 context；没有暗带 `photo_observation_v1` 或修改视觉提示。两臂共享这一新观察。

## 3. 反馈与修正授权

反馈固定包含：`failed_node=ui_architect`、`detected_by=coordinate_quality_gate`、object ID、field、该字段实际 raw value、constraint、evidence ref、allowed change、repair target、acceptance。

反馈同时携带首次完整架构 JSON、首次原始响应及两者 SHA256。修正返回完整 JSON；首次和修正 raw response 分别保存在 attempts 与 runner 产物中。

授权按 `(object_id, field)` 校验，不使用全局字段集合：

- 反馈顶层 `allowed_changes` 只列本次失败对应的对象与字段；`supported_fields_not_authorized` 仅说明门禁认识的字段类型，不构成修正授权。

- e1 的 bbox 错误不能授权改变 e2 的合法 bbox。
- `derivation.evidence_refs` 的错误不能授权修改 `derivation.reason` 或 `kind`。
- ID、vision ID、origin、type、text、parent 和 action 始终不可变。
- 每次修正记录 first→repair diff、原合法不变量保持分子/分母及编译产物 hash。

## 4. 下游失效与留证

supervisor 返回架构前明确清空旧 `ui_state_json`、`final_code`、`browser_audit`，并把失效事件追加到 `downstream_history`；首次 raw、首次诊断、反馈和 route history 不删除。复验通过后才产生新 HTML；仍错则 release gate 为 blocked。

PipelineTrace 记录 attempt、quality、feedback、route、输入/编译/HTML hash。硬错误、未决、语义未评估分开。

## 5. 对照 runner

入口：`scripts/run_feedback_loop_comparison.py`

CLI：

`python scripts/run_feedback_loop_comparison.py --case PATH --state NEW_DIRECTORY`

- `--state` 必须是新目录，避免复用运行中或旧状态。
- 总上限：共享 vision 1 + 共享 architect first 1 + candidate repair 最多1；不调用 coordinator/planner/reviewer。
- runner 使用同一 first attempt 初始化两份真实 LangGraph UI 子图状态。
- runner 按已确认 target 参数在冻结 prompt 后显式追加“目标设备：电脑网页；目标画布1440×900。”，再拼入口述；完整 `effective_request.txt` 及 SHA256 在调用前落盘，并同时作为旧视觉 legacy user context 与架构 intent。
- 输出 `state/run.json`、`state/results.zip`；run 记录 actual batch、PID、HEAD、Python、开始/结束时间、输入 hash、实际调用数、usage、状态和 expected archive。
- batch 内 `artifact_manifest.json` 记录除自身外全部内部文件 SHA256；归档完成后 run 记录 archive SHA256。
- 失败分支保留已发生调用记录、输入、已返回原响应和原始异常类型，不落凭据或异常 header。
- 本机 dry-run 已用冻结 002 case 验证状态目录、manifest 和 ZIP 生成，模型调用为0。

## 6. 测试结果

本机系统 Python：

- 62项测试被发现；55项实际执行并通过，0失败、0错误。
- 7项真实 LangGraph 子图执行测试因本机没有 `langgraph` 明确跳过。**不把这些跳过写成图通过。**
- 已执行的测试覆盖：实际请求使用新 prompt、可信上下文、反馈原答传递、raw parse失败保留、runner dry-run、坐标/来源链及旧相关回归。
- `py_compile` 与 `git diff --check` 通过。

待导师在已确认具备 `langgraph/langchain_core/openai` 的原 Ubuntu UV 执行7项子图测试，重点覆盖：发现→返回→修正→复验 trace、baseline 不修正、首答通过未触发、旧下游失效、不可变字段退化、按对象 bbox 授权、derivation 叶字段授权。完成该独立复核前不得启动真实模型轮或宣称图已运行通过。

## 7. 变更文件

- `src/prompts/ui_architect_target_layout_v1.md`（导师创建，本实现真实接入）
- `src/agents/ui_architect.py`
- `src/graph/ui_feedback_graph.py`
- `scripts/run_feedback_loop_comparison.py`
- `tests/test_ui_architect_target_attempt.py`
- `tests/test_ui_feedback_graph.py`
- `tests/test_feedback_loop_runner.py`
- 继续复用 T-LG-001 的 `src/utils/coordinate_contract.py`、`src/utils/architect_target_layout.py` 及相关测试。

未修改视觉提示、区域算法、渲染算法、ASR/选帧、GT；未调用模型、未远端、未恢复定时、未提交或推送。`scripts/launch_langgraph_feedback_round.py` 由导师维护，本任务未触碰。

交接人：质检员
