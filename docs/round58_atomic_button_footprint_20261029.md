# 轮58：区域分配与原子按钮尺寸分离

1. 用户失败与证据：57原始新HTML的加号373×130、麦克风163×130、返回164×82；截图中按钮被撑成大片区域。主输入两组已原生1/1，57新增类型转换0，不把跨轮输入恢复归因规则。消息、双方头像、个人资料操作仍不足。
2. 原因：symbolic_flow_layout.place给每个叶子placement=[0,0,1,1]，原子button填满分配区。这是代码布局引入，非视觉标签或模型必须如此。区域容器与其中控件职责混用；所有对象的父关系仍不自动获得语义证明。
3. 导师判断：tech-paper-template一致性检查1/3/4要求用户失败→模块→证据相符，本次只处理按钮撑满区域。idea-evaluator归因纪律：57原生输入确认不是收益；该机制未触发并非被数据否定，保留可选不重复采样强求触发。56/57整体无新收益后重新定位实际渲染/分配代码，不继续提示或边框阈值循环。本轮是工程设计，无论文创新声明。
4. 目标后复读既有链路调研MM-WebAgent全局/局部职责分离及WebVIA操作验收；借鉴分工，非复现。单机制：保持同一新投影树、区域分配、原始身份/文字/类型/动作/父关系；只对type=button叶子采用显式原型默认尺寸，居中放在原分配区。高度min(区域高,48px)；宽度min(区域宽,max(48px,24px+标题字符预算))，宽字符14px、窄字符8px。不是字体精测或草图比例恢复；不得把字体估计称真实测量。原最小24px/区域不变，不挤邻居、不重分余量；list、image、input、内容区不套按钮规则。超长标题可能仍受区域限制，必须浏览器读scrollWidth检查新增裁字。

配对：baseline同新投影默认填充，candidate同投影+按钮footprint；两组都不启用57类型锚点，防止混入第二机制。2共享视觉/架构物理调用、各有效2/独占0，8192/600秒/零重试，无Coder/新依赖/GT/选帧ASR重跑/旧HTML修补。

主验收：按全部原生button固定分母，分别报告原来过高(>48px)与处理后数量，处理触发数/可处理数；浏览器按钮真实尺寸符合声明且无新增标题裁切，至少一原过高按钮变小，截图确有可见改善方可称局部收益。不能以工程阈值达标替代页面合理比例，保留空白增多/控件锚点或视觉组织退化的手审。退化：全部ID/文字/类型/动作/父关系不变、区域树/分配不变、按钮只在自己原区内、非button坐标不变、无新增越界/遮挡，主输入固定1与七操作任务不下降。标签提示仅点击确认，非真实发送或业务成功。无原过高按钮记未触发；页面整体完整度/层级正确不能因小按钮改进称达标。
5. 实施验证：先工程检查，保存源码版本和两个原始新分支；通过后同次启动Ubuntu独立检出原UV有界生成。结果待下次验收。
6. 下一步：若仅缩小但组织更散/文字裁切/操作下降则拒绝默认启用，不调字号阈值反复救；若确有局部收益仍须分开处理缺失消息、个人入口与区域比例，不能默认推广13开发例。仅002开发、同实施者非独立人工，冻结论文指标不变。

## 实施与启动回执

本机83/Ubuntu原UV83工程检查、Python/JS语法通过，工程检查不代表收益。代码7239730f8742d0b3393f99da16b76149edcf94e5已推送，完整verified bundle独立检出/wyw/meeting_agent_workspace/my_agent_button_footprints_7239730；原UV3.12.13，无安装、三输入哈希不变。PID147017，UTC23:39:30实际run.json确认running、物理cap2；状态/wyw/meeting_agent_workspace/my_agent/outputs/optimization_cycles/round58_20261028T233930Z_button_footprints；批次/wyw/meeting_agent_workspace/my_agent/outputs/optimization_cycles/round58_20261028T233930Z_button_footprints/results/20261028T233930Z_49552e70；预期ZIP /wyw/meeting_agent_workspace/my_agent/outputs/optimization_cycles/round58_20261028T233930Z_button_footprints/results.zip，日志/wyw/meeting_agent_workspace/my_agent/outputs/optimization_cycles/round58_20261028T233930Z_button_footprints.worker.log。当前/设计/窗口/闭环与57终态均已写回；不在本次重复验收或启动58。
