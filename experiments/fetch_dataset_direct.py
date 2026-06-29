import urllib.request
import os

print("🔄 绕过依赖库，正在通过直链下载达摩院官方测试音频...")

# 确保目录存在
os.makedirs("/wyw/meeting_agent_workspace/my_agent/experiments/dataset", exist_ok=True)
save_path = "/wyw/meeting_agent_workspace/my_agent/experiments/dataset/sample_meeting.wav"

# 阿里官方 OSS 直链，极速无墙
url = "https://isv-data.oss-cn-hangzhou.aliyuncs.com/ics/MaaS/ASR/test_audio/asr_example_zh.wav"
ground_truth = "欢迎大家来体验达摩院推出的语音识别模型"

# 直接下载
urllib.request.urlretrieve(url, save_path)

print("\n✅ 下载成功！纯净无依赖方案就是爽！")
print(f"📁 音频已保存至: {save_path}")
print(f"📝 官方标准文本 (Ground Truth): {ground_truth}")
print("\n💡 提示: 请将上面的标准文本，复制到 benchmark_asr.py 的 GROUND_TRUTH 变量中，准备跑分！")
