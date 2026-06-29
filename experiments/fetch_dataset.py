from datasets import load_dataset
import soundfile as sf
import os

print("🔄 正在连接 HuggingFace 获取安全的开源数据集 (PolyAI/minds14 中文普通话)...")
# 现代 Parquet 格式，直接拉取，不需要任何危险的 script 权限
dataset = load_dataset("PolyAI/minds14", name="zh-CN", split="train", streaming=True)

# 提取第一条样本
sample = next(iter(dataset))
audio_array = sample["audio"]["array"]
sampling_rate = sample["audio"]["sampling_rate"]
ground_truth = sample["transcription"]  # 获取标准转写文本

# 确保目录存在并保存为 wav 文件
os.makedirs("/wyw/meeting_agent_workspace/my_agent/experiments/dataset", exist_ok=True)
save_path = "/wyw/meeting_agent_workspace/my_agent/experiments/dataset/sample_meeting.wav"
sf.write(save_path, audio_array, sampling_rate)

print("\n✅ 测试数据拉取成功！")
print(f"📁 音频已保存至: {save_path}")
print(f"⏱️ 采样率: {sampling_rate} Hz")
print(f"📝 官方标准文本 (Ground Truth): {ground_truth}")
print("\n💡 提示: 请将上面的标准文本，复制到 benchmark_asr.py 的 GROUND_TRUTH 变量中进行测试。")
