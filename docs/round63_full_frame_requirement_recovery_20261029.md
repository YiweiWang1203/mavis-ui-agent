# 轮63：冻结需求槽机制在完整帧链路的主输入恢复

1. 用户失败：62两组仍无原生主输入，消息和角色缺失；历史标题被列表覆盖、语音被发送覆盖。62仅坐标改动没有恢复任务。主目标收敛为可输入，而非再次调整所有位置。
2. 定位：同源视觉与架构将“输入框”保留为text；受控渲染忠实生成文字。23已在旧裁图开发例证明原文槽绑定可恢复输入，但不能推定完整帧当前链路同样有效。62已有目标位置保留策略不推广，恢复基线布局以单独检验类型。
3. 导师判断：idea-evaluator fatal-flaws §6要求不为无收益布局机制辩护；本次是冻结已存在机制的新输入链路回归，不称新方法创新。tech-paper-template一致性1/3/4将明确编辑原意、类型编译、实际填入读回对应；不以填入通过声称消息/层级/比例解决。目标后复读链路调研“组件语义落实”、系统设计Observation/语义/布局职责与23卡。仅借鉴分工，非论文复现。
4. 固定单机制：同一次新视觉+架构生成基线；候选对同一基线运行原requirement_slots_v1与保守text→input编译。槽由代码从冻结口述截取，模型只绑定槽ID到已有视觉ID或null，不能写新引文。编译器原样冻结，不扩规则、不改提示。源标签/否定/类型/唯一身份校验保留。新比较保护器限制元素唯一变化为有接受原文证据的text→input及其证据字段，任何文字/动作/父/坐标/新增删除变化失败。

预算最多3物理请求，共享视觉/架构2，候选绑定独占最多1；有效基线2/候选最多3，不称等调用消融。无合格槽时0绑定调用并记未触发，不能为有结果而调用。8192/600秒/零重试，同原UV模型，无安装、换帧、ASR、GT、旧HTML修补。

主验收：原文明确要求的主聊天输入实际填入读回1/1；搜索不替代。绑定语义逐槽审查，未决/原生已有另报；若基线已1/1只记保持，若缺身份不得补造。固定七入口逐项实操，保持所有基线可操作项、PC1440×900、位置/尺寸/身份/文字/父关系一致、0新增越界/遮挡。输入变可编辑不保证发送后端或整个聊天页可用；既有历史/语音遮挡及消息遗漏完整保留。无HTML不填操作分。
5. 先检查保护器及冻结绑定器，再独立检出真实生成，保存原请求响应、源哈希、接受/未决、UI-State、HTML和浏览器截图。
6. 有效只保留可选输入机制，之后针对缺失语义或区域职责选一项；无效按绑定/类型/渲染定位，不重采样或放宽引文规则。单例开发、同实施者非独立复核，冻结论文评分不改。


## 实际启动
代码 94de0384fbfd6a3694c3715101782889c9ad7aaf 已推送；本地56检查、Ubuntu适用门槛41检查均通过，0跳过，无安装。UTC02:12:44运行，原UV /wyw/meeting_agent_workspace/my_agent/.venv/bin/python，PID150544。独立检出 /wyw/meeting_agent_workspace/my_agent_full_frame_requirements_94de038；状态 /wyw/meeting_agent_workspace/my_agent/outputs/optimization_cycles/round63_20261029T021241Z_full_frame_requirements；实际批次 /wyw/meeting_agent_workspace/my_agent/outputs/optimization_cycles/round63_20261029T021241Z_full_frame_requirements/results/20261029T021244Z_68fccd25；预期ZIP /wyw/meeting_agent_workspace/my_agent/outputs/optimization_cycles/round63_20261029T021241Z_full_frame_requirements/results.zip；日志 /wyw/meeting_agent_workspace/my_agent/outputs/optimization_cycles/round63_20261029T021241Z_full_frame_requirements.worker.log。三个冻结输入哈希见current_remote.json，均核对一致。最多3物理调用，零重试，效果待下一次验收，不同次连跑。


## 终态：身份缺失未决，无输入恢复
ZIP b8c34ec5ae4ebcafd992d355515af303e6721a143da64d0dd68e03907c4b6678；47内部/186源码/3输入哈希通过。3物理请求5104token/47.659267秒，基线有效2、候选3（共享2/独占1），非等调用消融。原文槽293:362含明确编辑要求，1槽/1评审、r1→e5“对话内容”原始提议被literal_label_not_anchored拒绝；绑定0/1、转换0、未决1/1，既有原生0。新视觉8对象无输入身份，不改拒绝规则、不把会话文本硬转输入。两组8对象和HTML完全相同，实操主输入0/1；七标签提示5/7、个人入口缺失、发送被语音遮挡超时。人工查看头像e4为被动image，无资料反馈，不挑别的按钮冒充成功。尺寸8/8、0越界、ID唯一、原HTML操作前后不变；两图已查看。消息与角色仍未拆分，不能因跨轮历史能点而归因机制。导师区分适用前提缺失与机制交付：不推广、不放宽字面，下一轮64独立spoken实体补全，保存观察/目标空间及缺失决定，原字段不改。详review.json及browser/audit.json。
