import time
import jiwer
import wave
import contextlib
import torch
from funasr import AutoModel

TEST_AUDIO = "/wyw/meeting_agent_workspace/my_agent/experiments/dataset/sample_meeting.wav"
GROUND_TRUTH = "欢迎大家来体验达摩院推出的语音识别模型"

def get_audio_duration(file_path):
    with contextlib.closing(wave.open(file_path,'r')) as f:
        return f.getnframes() / float(f.getframerate())

def run_funasr():
    print("--- 🏁 启动参赛选手 2: FunASR (Paraformer) [RTX 4090 满血版] ---")
    
    # 诊断 GPU 状态
    is_cuda = torch.cuda.is_available()
    print(f"🔬 诊断 - PyTorch CUDA 是否可用: {'✅ 是' if is_cuda else '❌ 否 (请检查PyTorch是否为GPU版本)'}")
    if is_cuda:
        print(f"🎮 识别到显卡: {torch.cuda.get_device_name(0)}")
    
    # 强制挂载到第一块 4090 上
    device_str = "cuda:0" if is_cuda else "cpu"
    print(f"🔄 正在加载模型至 [{device_str}] ...")
    
    # 加载模型
    model = AutoModel(model="paraformer-zh", model_revision="v2.0.4", device=device_str)
    
    audio_duration = get_audio_duration(TEST_AUDIO)
    print(f"▶️ 测试音频时长: {audio_duration:.2f} 秒")
    
    # 预热 (GPU 第一次推理会有显存分配等冷启动延迟，测速前先跑一次空弹)
    print("🔥 GPU 引擎预热中 (跑一次空弹)...")
    _ = model.generate(input=TEST_AUDIO)
    
    print("🧠 正式计时推理中...")
    start_time = time.time()
    res = model.generate(input=TEST_AUDIO)
    end_time = time.time()
    
    # 核心修复：干掉输出结果中的空格，还原真实的识别率
    result_text = res[0]['text'].replace(" ", "")
    
    inference_time = end_time - start_time
    cer = jiwer.cer(GROUND_TRUTH, result_text)
    rtf = inference_time / audio_duration
    
    print("-" * 40)
    print(f"📝 官方答案: {GROUND_TRUTH}")
    print(f"🤖 识别结果: {result_text}")
    print("-" * 40)
    print(f"📊 [FunASR + RTX 4090 成绩单]")
    print(f"🎯 字符错误率 (CER): {cer:.4f} (0.0000 表示全对)")
    print(f"⏱️ 纯推理耗时:       {inference_time:.4f} 秒")
    print(f"🚀 实时率 (RTF):     {rtf:.4f} (越低越快)")
    print("-" * 40 + "\n")

if __name__ == "__main__":
    run_funasr()
