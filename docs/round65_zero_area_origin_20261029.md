# 第65轮八个零面积框的原始来源核查

已核对 shared_upstream/call_02.json 的完整实际请求和原始响应字符串，与009解析结果完全相等；无图片附件，Qwen/Qwen3-VL-8B-Instruct正常stop，865输出token，无截断。八对象为返回、搜索、历史对话、对话内容、个人头像、上传、发送、语音；不是页面外框，也不是八个新增对象。

每个原始响应bbox确实为[1440,900,1440,900]，表示目标右下角同一点，非[左上x,左上y,宽,高]。008上游各归一化框有面积，009至011保留坏框，012用上游归一化框乘1440/900替换，具体表见 zero_area_origin.json。

实际system一方面要求所有elements有page-global像素bbox，另一方面说normalized vision boxes will be converted by local code, so do not redesign visual geometry，并只特别要求spoken-only additions提供valid page-global boxes。这使视觉对象坐标究竟由模型还是代码负责不明确。代码确实将视觉对象坐标视为可覆盖字段。

原始坏数值来自模型是事实；由这段职责表述导致模型输出坏框只是待验证假设，不能凭一次响应读出模型思考，也不能断言一定是能力不足。新严格门禁要求的coordinate_provenance/coordinate_space/viewport_id/derivation并未在旧请求schema中要求，缺这些字段不能反向算旧模型违规；正面积错误仍成立。

导师决策：不能将首轮等同于让模型反复修一个生产中本来会被覆盖的占位字段。先明确唯一坐标责任方及与实际提示的契约一致性。硬错误拦截有工程价值，不能仅把8/8拒绝作为页面收益。来源链漏洞修复仍可继续，视觉/布局新实验方案待讨论。
