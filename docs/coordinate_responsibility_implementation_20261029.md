# 坐标职责与传递契约：实施卡与第65轮诊断交付

日期：2026-10-29。状态：代码与自动检查完成，待独立验收；映射算法待用户讨论。本轮没有模型调用、Ubuntu 生成、HTML 生成、第66轮或定时恢复。

## 一、实施卡（改动前固定）

### 项目六步

1. **用户失败**：架构原答的目标 placement 非法，但身份编译用照片观察 bbox 覆盖原答，后续 HTML 看不到首错。
2. **机制定位**：`finalize_ui_state → build_structure` 的生产路径未使用现有 D1 `coordinate_contract.py`；`coordinate_contract=null` 时执行旧的 `image_norm × viewport`。
3. **可证伪假设**：若在覆盖前独立校验观察帧、目标 viewport、逐元素空间/尺寸/来源，则第65轮 8 个零面积框应全部被拒绝且原值可追踪；合法显式双空间应通过且不触发照片缩放。
4. **最小实现**：复用现有 D1 契约与 `architect_target_layout`，只新增覆盖前审计/严格门禁；严格模式失败即停止，通过则保留架构目标 placement。默认旧模式不变。
5. **配对验证**：合成合法双空间与非法/缺失分支测试；使用第65轮既有 JSON 只读回放，不生成页面。
6. **决策门槛**：本轮只证明非法传递可被阻断。照片到电脑画布的映射、区域模板或新增模型请求均保持 `pending_user_decision`。

### 失败—机制—证据

| 失败 | 机制 | 本轮证据 |
| --- | --- | --- |
| 架构零面积框被掩盖 | 旧身份编译覆盖 `spatial_info.bbox` | 009 原框与 012 替换后框；严格回放 8/8 拒绝 |
| 照片观察与目标布局混用 | 旧路径直接将归一化视觉框乘 target viewport | 003/005 canvas 与 009 viewport 分离记录；严格模式不调用旧路径 |
| 缺空间/来源仍继续 | 原结构没有强制 `coordinate_space`、`viewport_id`、`derivation` | 每个第65轮对象均报告四类问题，不靠数组范围猜空间 |
| 部分 placement 或坏数值被模糊处理 | 缺统一分母和逐对象诊断 | 报告 element/valid/invalid/skipped，并覆盖缺失、非有限、越界、零面积 |

### tech-paper-template 一致性 1 / 3 / 4

- **检查1（局限→目标）通过**：局限是覆盖掩盖首错与空间职责缺失；目标仅为覆盖前诊断和显式职责门禁，没有宣称恢复漏检或页面布局。
- **检查3（挑战→方法）通过**：原框保留对应逐元素只读诊断；双空间职责对应 frame/viewport 独立 provenance；坏框与缺来源对应严格拒绝；旧基线兼容对应 opt-in 模式。
- **检查4（方法→交付主张）通过**：交付只主张工程阻断、来源追踪和自动测试；没有把第65轮回放写成页面改善、映射正确或独立验收通过。

## 二、实际调用链

- 旧基线（默认）：`finalize_ui_state → build_structure → solve_hierarchy`，行为未变。
- 严格候选：设置 `UI_COORDINATE_RESPONSIBILITY_MODE=strict_v1` 后，`finalize_ui_state → audit_architect_coordinate_responsibility`。
  - 诊断失败：抛出带 `diagnostic` 的 `CoordinateResponsibilityError`，不进入身份覆盖、布局求解或 HTML。
  - 诊断通过：复用 `compile_architect_target_layout → build_structure(coordinate_contract=...) → apply_coordinate_contract`；保留目标 placement，观察 geometry 单独挂载，`implicit_photo_to_viewport_mapping=false`。
- 严格模式要求上游显式提供 `page_meta.coordinate_provenance.observation_frame`（ID、尺寸、SHA256）与 `target_viewport`（ID、尺寸），并要求每个 placement 声明 `viewport_px`、viewport ID 和 derivation。该入口不提供映射算法。

## 三、改动文件

- `src/utils/coordinate_contract.py`：新增机器可读诊断、严格异常和有限数/正面积/越界/空间/viewport/推导/覆盖检查；原输入不变。
- `src/agents/ui_architect.py`：增加 opt-in 严格调用链；通过后复用现有 D1 target-layout 编译，失败时阻断。
- `tests/test_coordinate_contract.py`：增加合法双空间、零面积、缺空间/推导、placement 部分缺失、非有限/越界和照片尺寸覆盖目标的测试。
- `tests/test_architect_target_layout.py`：增加严格生产调用链通过与覆盖前失败测试。

## 四、自动测试

命令：

`python -m unittest tests.test_coordinate_contract tests.test_architect_target_layout tests.test_hierarchy_contract tests.test_region_layout_contract tests.test_placement_contract`

结果：48 个测试方法通过，0 失败、0 错误。异常测试中的多个分支不冒充独立页面样本。未运行全仓测试、浏览器测试、模型测试或 Ubuntu 测试。

## 五、第65轮只读回放报告

证据源：`outputs/optimization/round65_unique_binding/unpacked/20261029T031203Z_e39e448c/shared_upstream/pipeline_trace`。

### 009 → 011 → 012

- 分母 8；有效 0；非法 8；跳过 0。
- 8/8 原始 bbox 均为 `[1440,900,1440,900]`，全部在覆盖前以 `invalid_target_bbox` 拒绝，原值保留在逐元素诊断中。
- 8/8 同时明确报告 `missing_or_wrong_coordinate_space`、`missing_or_wrong_viewport_id`、`missing_derivation`。
- `mapping_strategy=pending_user_decision`，`implicit_photo_to_viewport_mapping=false`。
- 因诊断为 `rejected`，严格候选不会进入 012 式覆盖，也不能交付标为通过的 HTML。

### 003 → 005 来源追踪

- 003 的 8 个源 bbox 到 005 数值保持 8/8；跳过 0。
- 003 模型返回 canvas 为 1440×900；005 照片观察 canvas 为 406×720；009 目标 viewport 为 1440×900。
- 照片帧 SHA256 使用 001 已登记值 `340bfd115af912a98a074bc77a8eb00248e8d9e8d47578a0af79b800a495c7c6`。
- 406×720 只属于 observation frame；没有替换 1440×900 target viewport。003 的模型 canvas 声明与 005 的真实照片尺寸不一致被作为来源事实保留，不能据此推断模型实际坐标语义。

## 六、兼容性、限制与回滚

- 兼容性：默认 `off`，既有旧路径和测试保持；严格模式是显式 opt-in。严格模式要求上游补齐 provenance 与逐 placement 声明，否则按设计拒绝。
- 已知限制：只验证契约、数值与引用存在，不验证布局语义是否正确；不恢复视觉漏检、层级、交互或区域规划。
- 回滚：移除 `UI_COORDINATE_RESPONSIBILITY_MODE=strict_v1` 即回到旧基线；代码级回滚仅涉及上述两个源码文件和两个测试文件。
- 独立验收：尚未进行，不得写为任务完成或页面效果改善。

交接人：质检员
