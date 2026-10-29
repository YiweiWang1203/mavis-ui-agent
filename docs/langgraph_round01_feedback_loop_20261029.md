# T-LG-002 首轮：真实LangGraph有界反馈回路

更新：真实轮66已完成，发现/定位/返回/再次检查均触发，来源修正失败0/1，无HTML。完整逐层验收见 `docs/langgraph_round01_feedback_loop_acceptance_20261029.md`，原包及30内部哈希已核验；本窗口已消耗第1/20轮。

用户已认可优先发现—定位—返回—修正，并要求立即修复坐标职责歧义。窗口第1/20轮准备中；全局实验编号拟66，工程和回放不计效果轮。

用户失败：架构坏布局未驱动调度修正，被旧代码照片缩放覆盖；仅执行步骤不检查输出质量。
证据：round65原始call_02/009/012；supervisor parsed_plan按步推进。8坏框来自模型但旧提示明确说代码会转换视觉框，不能只归模型能力。
导师判断：限定验证反馈路由机制，不声称新增节点即有效。参考ReAct reasoning/action交替、Reflexion反馈用于后续行动；当前仅借鉴职责与反馈，不复现其训练/记忆或宣称性能。既有系统设计/来源核查已复读。

单机制：共同的新目标布局契约及同一初次新生成架构，baseline检测后终止，candidate仅在确有失败时由真实LangGraph supervisor返回ui_architect一次，将代码诊断作为定向反馈；复验通过才渲染，仍错明确停止。
控制条件：同一新观察、首次架构、实际prompt、照片/ASR/目标画布、渲染和硬门禁；唯一差异是失败后是否允许一次修正。不与旧照片缩放路径作因果对照；旧65仅诊断。

职责修正：新prompt src/prompts/ui_architect_target_layout_v1.md 明确模型拥有所有target placement，照片bbox仅证据，代码不缩放/覆盖/猜变换。旧prompt仅复现旧入口，反馈新路径不得使用。先核实与严格契约实际字段一致；frame/目标ID由可信调用者代码传入，不向模型索取真实hash。

实现要求：
- 使用LangGraph真实图节点/Command/State，不把Python手工for循环包装成已验收LangGraph。可使用已有节点组成有界UI子图，须明确这是UI子图，不冒称coordinator/planner/ASR均运行。保留旧模式。
- 首次架构和修正原始响应分别保存；失败不可被generate_ui_state通用except吞成字符串并丢失diagnostic。代码结构化检查为本轮review，无新增语义审查模型。
- feedback: failed_node/object_id/field/raw_value/constraint/evidence_ref/allowed_change/repair_target/acceptance；未知错误必须停止，不能随意重做视觉。
- 最多修正一次；保持视觉、语义库存和未指明字段。新增删对象、type/text/action/parent无授权变化为修正退化，拒绝。布局依赖变化须记录。
- 修正前清空旧ui_state_json/final_code/浏览器验收等下游衍生状态，保留原答/attempt历史；不能交付旧HTML。
- 各阶段输入/输出、hash链、attempt、route、质量分母、变更diff、真实模型预算计数埋点；硬错误和未决不等同。

实验：冻结002完整帧与口述，最多3物理请求：共享观察1、共享首次架构1、候选独占修正最多1。若首答通过，不为强迫触发再请求或注入错误；报告机制未触发。若API失败0自动重试。每请求8192输出token/600秒。不能漏算coordinator/planner/reviewer；本轮用显式预设UI子任务避免额外隐藏模型调用。初始语义/区域质量未改变，不能声称全部融合解决。

验收：实际LangGraph有发现→定位→返回→修正→复验 trace；目标坐标非法数/架构对象数；原合法字段保持数/应保持字段数；错误下游交付数；操作和内容/归属/遮挡手审。只拦错不算页面改善；修后数值合法也不自动算语义正确。无HTML不填功能分；有新HTML必须实操/截图/哈希后给预览。不得人工改旧HTML。

阶段状态：先工程实施/自动检查与导师复核，再限定提交推送/独立Ubuntu原UV执行。工程师不自行付费调用/远端启动；交付可运行脚本、支持旧记录终态防并发的启动方案。当前自动化不恢复。
