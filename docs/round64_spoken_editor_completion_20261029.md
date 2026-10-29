# 轮64：缺失可编辑对象的口述来源补全

1. 用户失败：63主聊天输入仍0/1。新视觉8对象中根本没有输入框，口述原句293:362明确“最下方是我的输入框，输入框是可以输入文字的”。旧槽提议r1→e5“对话内容”，因标签不在原句被正确拒绝；接受0/1、未决1/1、类型转换0，没有HTML改善。不能把本次正确拒绝称需求满足，也不能放宽标签规则把会话内容变输入。
2. 定位：63冻结机制只支持已有视觉身份绑定，当前失败先于类型编译。源观察集合不能被当作完整需求集合。完整图上草图底部编辑框可见，但标准观察漏检；新增路径须保留两种来源，避免凭期待伪造视觉ID。
3. 导师判断：idea-evaluator区分前提缺失与已匹配机制被否定；不推广63为普遍恢复、不调字面门槛。本轮转到独立spoken来源补全，tech-paper-template一致性1/3/4对应“明确要求→独立实体→原生填写”，仅验证可编辑对象这一窄范围。目标后复读系统设计§3—4跨源语义计划、链路调研身份来源与组件落实、23/63证据；MM-WebAgent职责分工只是启发，本实现非复现。
4. 单机制：共享新视觉+原架构两请求生成原基线。候选一次多模态请求只处理代码生成的明确编辑需求槽：逐槽existing（引用已有对象）、missing（独立spoken实体）、unresolved。missing须同时报完整帧观察框image_norm与目标viewport_px布局框，两者另存，绝不相乘推导；模型不生成引文/ID/类型/动作，代码从原文槽保存偏移并创建input与稳定spoken ID。既有对象一个字段也不改。已有匹配仅原生input确认，非原生角色不在本轮转型。已有原生编辑控件时禁止再补；重复槽相互重叠、任一目标框与任一原有bbox正面积相交、越界、微小框均拒绝，不自动夹入/避让/重试。source框仅作为待手审观察提议，数值合法不是视觉身份成立；missing判断和语义重复必须手审。未决不给新增，0/0不当通过。只针对明确输入表达，不扩到任意消息/按钮或造区域树。

预算≤3物理请求：新视觉/架构共享2，候选最多独占1；有效2/最多3，非等调用消融。8192/600秒/零重试，同原UV/模型/冻结图口述，无新依赖/GT/换帧/ASR/HTML修补。原绑定器冻结不改，不把新机制冒充旧机制通过。

主验收：主聊天输入实际填写读回1/1，且独立source框确实落在草图编辑区、目标框符合口述区域关系；任何一项失败不称完整补全。原有ID/文字/类型/父/动作/位置/尺寸全保留；七入口所有基线成功项保持、0新增遮挡/越界，重复主编辑器0。新input不是增加元素数就通过。候选若因严格门槛失败保留错误，无候选HTML不填操作分。既有语音/发送遮挡、头像/消息缺失不在本轮解决，全部单列。
5. 保存前源码、原请求响应、槽/匹配未决/新增原始框/目标框、原HTML；工程检查严格拒绝身份改动、重叠/越界/重复及来源异常，真实生成后实操截图。
6. 有效只保留可选窄补全，后续冻结回归再接区域比例；无效按缺失判断/观察定位/布局/渲染分层，不救提示阈值。本例开发、同实施者非独立人工、冻结论文分不变。


## 实际启动
生成代码 5ca0f5698ab4163da4a6f55d3ddb6330c01dd1cc 已推送；本地45检查通过，Ubuntu适用门槛34检查通过，均0跳过；渲染集成测试初期fixture缺layout_solver标记已修测试fixture后通过，未放宽生产门槛。无安装。北京时间10:43:52启动，原UV /wyw/meeting_agent_workspace/my_agent/.venv/bin/python，PID151248。独立检出 /wyw/meeting_agent_workspace/my_agent_spoken_editor_completion_5ca0f56；状态 /wyw/meeting_agent_workspace/my_agent/outputs/optimization_cycles/round64_20261029T024349Z_spoken_editor_completion；实际批次 /wyw/meeting_agent_workspace/my_agent/outputs/optimization_cycles/round64_20261029T024349Z_spoken_editor_completion/results/20261029T024352Z_4719a6f6；预期ZIP /wyw/meeting_agent_workspace/my_agent/outputs/optimization_cycles/round64_20261029T024349Z_spoken_editor_completion/results.zip；日志 /wyw/meeting_agent_workspace/my_agent/outputs/optimization_cycles/round64_20261029T024349Z_spoken_editor_completion.worker.log。三个输入哈希与冻结案例一致，见current_remote.json。状态running，最多3物理调用，每阶段8192/600秒/0重试，效果待验收。
