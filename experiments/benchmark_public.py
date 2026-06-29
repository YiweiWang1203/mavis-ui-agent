import os
import time
import re
import torch
import jiwer
import soundfile as sf
from funasr import AutoModel

# 强制使用镜像，保证你能在几秒钟内连上 HuggingFace 数据集
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
from datasets import load_dataset

def normalize_text(text):
    """文本正则化：剥离所有标点和空格，保证 CER 计算绝对公平"""
    text = text.replace(" ", "")
    text = re.sub(r'[，。！？、,!?<>]', '', text)
    text = text.lower()
    return text

def run_benchmark():
    print("--- 🏁 启动 ASR 极限压测：公开高难度测试集 ---")
    
    # 1. 瞬间从云端流式抽取 1 条远场/口音数据
    print("🌐 正在连接云端拉取 AliMeeting (远场嘈杂会议) 数据样本...")
    try:
        # trust_remote_code=True 兼容部分自定义数据集格式
        ds = load_dataset("speechcolab/alimeeting", "Eval_Ali_far", split="test", streaming=True, trust_remote_code=True)
        sample = next(iter(ds))
    except Exception as e:
        print(f"⚠️ AliMeeting 拉取失败，自动降级切换至 Google Fleurs (中文口音数据集)...")
        ds = load_dataset("google/fleurs", "cmn_hans_cn", split="test", streaming=True, trust_remote_code=True)
        sample = next(iter(ds))

    # 提取音频阵列和采样率
    audio_array = sample['audio']['array']
    sample_rate = sample['audio']['sampling_rate']
    
    # 如果是多声道阵列麦克风数据，只取第一个声道
    if len(audio_array.shape) > 1:
        audio_array = audio_array[0]
        
    # 对于 AliMeeting，text 通常是列表或字符串，处理一下
    ground_truth = sample.get('text', sample.get('raw_transcription', ''))
    if isinstance(ground_truth, list):
        ground_truth = "".join(ground_truth)
    
    test_file = "/wyw/meeting_agent_workspace/my_agent/experiments/dataset/hard_public_sample.wav"
    sf.write(test_file, audio_array, sample_rate)
    audio_duration = len(audio_array) / sample_rate
    
    print(f"▶️ 获取成功！音频时长: {audio_duration:.2f} 秒，采样率: {sample_rate}Hz")
    
    # 2. 满血加载三合一 Pipeline
    is_cuda = torch.cuda.is_available()
    device_str = "cuda:0" if is_cuda else "cpu"
    print(f"\n🔄 加载模型 [{device_str}] (主力 Paraformer + 断句 VAD + 标点 PUNC)...")
    
    model = AutoModel(model="paraformer-zh", 
                      vad_model="fsmn-vad", 
                      punc_model="ct-punc", 
                      model_revision="v2.0.4", 
                      device=device_str)
    
    print("🔥 引擎预热...")
    _ = model.generate(input=test_file)
    
    print("🧠 正式计时推理中 (正在同时进行语音识别、端点检测和标点预测)...")
    start_time = time.time()
    res = model.generate(input=test_file)
    end_time = time.time()
    
    raw_result_text = res[0]['text']
    
    # 3. 严格计算公平指标
    norm_truth = normalize_text(ground_truth)
    norm_result = normalize_text(raw_result_text)
    
    inference_time = end_time - start_time
    cer = jiwer.cer(norm_truth, norm_result)
    rtf = inference_time / audio_duration
    
    print("\n" + "=" * 55)
    print("📊 [真实场景公开数据 - 压测成绩单]")
    print("=" * 55)
    print(f"📝 官方答案 (可能带口音或结巴): {ground_truth}")
    print(f"🤖 加上标点的实战输出:       {raw_result_text}")
    print("-" * 55)
    print(f"🎯 字符错误率 (CER): {cer:.4f} (真实恶劣场景下 < 0.15 即为工业级可用)")
    print(f"⏱️ 纯推理总耗时:     {inference_time:.4f} 秒")
    print(f"🚀 实时率 (RTF):     {rtf:.4f} (观察挂载3个模型后的速度损耗)")
    print("=" * 55 + "\n")

if __name__ == "__main__":
    run_benchmark()
