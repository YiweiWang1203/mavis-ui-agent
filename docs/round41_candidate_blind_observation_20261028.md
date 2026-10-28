# 轮41：候选盲观察与确定性匹配（实施前冻结）

1. 用户失败：008完整原帧已经产生覆盖整页的候选，但轮38—40最终选择局部框。轮40三臂首位追随3/3、整页0/3；文字顺序与接触图格位共同变化，单例不能证明普遍位置偏差。2026-10-28本次SSH复核原ZIP SHA仍为84944612a0d31f80e8d1e02dd7a55b6bdfc64c840c446219f98ca7368a0a26a8，无运行生成。
2. 原因与研究：正确候选缺失不是本例当前瓶颈。目标确定后复读既有架构调研、学术路线复核及user-centered-optimization；独立同名导师SKILL未找到。以下原始来源已核验：
   - Pezeshkpour, Hruschka. Large Language Models Sensitivity to The Order of Options in Multiple-Choice Questions. Findings NAACL 2024. https://aclanthology.org/2024.findings-naacl.130/ 。研究文本选择顺序敏感；不能当成我们的视觉错误成因证明。
   - Tian, Zou, Yang, Zhang. Identifying and Mitigating Position Bias of Multi-image Vision-Language Models. CVPR 2025. https://arxiv.org/abs/2503.13792 。多图位置敏感及SoFA注意力改造。无需训练不等于可用托管API直接部署；本轮不改模型内部，不冒称复现。接触图单张拼图与其多图序列不同。
   - Yang et al. Set-of-Mark Prompting Unleashes Extraordinary Visual Grounding in GPT-4V. 2023. https://arxiv.org/abs/2310.11441 ，官方 https://github.com/microsoft/SoM 。区域标记提供引用依据；我们现有编号接触图不是SoM复现，编号本身不保证整页身份。本轮不新增SAM或标记。
   三文提供诊断/职责设计依据，不直接给出本轮算法或有效性。候选盲观察与代码匹配是工程假设。
3. 假设：去掉观察阶段的候选列表与接触图，让模型从原始完整图独立估计手绘UI页面范围，可减少直接点选首位的捷径；代码仅在已有几何候选中匹配，不让语义模型创造最终外框。若范围仍漏内容、单位错误、匹配错或未决，目标未达。
4. 固定方案：冻结35有界两跳几何及完整历史原帧入口，基线简洁ID选择一次；候选盲观察一次，只见同一完整原图、原口述和图像宽高，不见候选或基线结果。唯一必输契约page_bbox=[left,top,right,bottom]为0—1、visible_ui_evidence非空文字、uncertain布尔；不确定时bbox=null且uncertain=true。观察的是页面外框轴对齐范围，非内部内容紧包围框、非纸边。严格拒绝1000尺度、不自动缩放/夹限。
   代码将每个已有quad的轴对齐范围与观察框计算bbox IoU（只是匹配分数，不是GT准确率），最高分至少0.85且领先次高至少0.02才选。阈值为预先固定工程启发，不由本例正确ID调参；接近候选可能因此未决。排序同分不择首。最终quad及来源原样保留，观察bbox不直接成为输出边界。不用最大面积替代身份；纸/桌假框和错误观察仍可能通过，必须语义目检。
   两组同新几何，实际最多2物理调用（各1），Qwen/Qwen3-VL-8B-Instruct、8192/600秒/零重试，温度0；无额外取证、深网、安装、HTML。空候选双方不调用。
   主指标：整页候选存在1/1、最终整页正确各1/1、内部/纸/桌误选0；未决/契约/API失败分别报告。观察内容是否覆盖原图所有主要UI、原始归一化范围合理性手审。报告同源候选字节/输入哈希、全部匹配分数、成本。无GT不报GT IoU/角点准确率。边界实验无HTML，不填浏览器功能分。
5. 实施验证：代码、测试、独立原UV检出、新原始请求响应和ZIP写入运行记录；先保存旧源码快照与git差异。不得用旧响应、重排正确ID、重试挑优或放宽阈值。008为开发例、同实施者审查非独立人工。原始视频PTS/历史预处理Git仍未知，未重新选帧或ASR。当前8770仍23轮旧HTML。
6. 下一轮决定：真实结果后填写；未验证前不默认启用，不称解决全部层级或可用网页。成功后先另一小开发例冻结回归，再推进页面→画布→区域→元素。
