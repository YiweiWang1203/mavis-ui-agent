
模型矩阵说明（已恢复为官方推荐组合）
=================================

说明：经回归测试，项目中采用的 FunASR 使用的是“主 ASR + 可选 VAD/PUNC/SPK” 的组合方式（由 `AutoModel` 在底层串联）。因此仓库中保留了各个独立模型目录，并由 `src/tools/asr_tool.py` 在本地可用时按绝对路径加载，或回退为 ModelScope ID 下载。

当前保留与使用的模型
- 主听写（本地优先）：`data/models/iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-online` 或 `data/models/iic/speech_paraformer-large-vad-punc-spk_asr_nat-zh-cn`（如存在）
- VAD：`data/models/iic/speech_fsmn_vad_zh-cn-16k-common-pytorch`
- PUNC：`data/models/iic/punc_ct-transformer_zh-cn-common-vocab272727-pytorch`（若本地存在）
- SPK（说话人）：`data/models/iic/speech_campplus_sv_zh-cn_16k-common`
- 多模态视觉：`llava`
- 中央推理模型：`deepseek-r1:14b`

已完成的工作
- `src/tools/asr_tool.py`：已恢复为官方推荐的 `AutoModel(model=..., vad_model=..., punc_model=..., spk_model=...)` 初始化方式，并在本地模型存在时使用绝对路径以避免网络下载。工具同时生成结构化 JSON（Meeting-Transcript 规范）与人类可读的规范化 TXT，供 downstream 使用。 

关于冗余模型的处理
- 已将不再需要的备份或旧版本模型移动到 `data/models/archive/`（或可改为归档策略），生产环境请保留必要的本地权重以避免网络失败导致的 404。

建议
- 1) 让 `meeting_agent` 的处理链优先读取 `.json`（结构化）文件以完成跨模态对齐与业务抽取；
- 2) 保持 `asr_tool` 输出 JSON 中包含精确的 `start_time` 与 `end_time`（秒，浮点），便于后续与视频/画面对齐；
- 3) 仅在必要时更新本地模型目录，并记录版本信息到 `ARCHITECTURE.md`。

维护人
- 建议由 `meeting_agent` 维护者负责模型更新、验证与归档流程。
