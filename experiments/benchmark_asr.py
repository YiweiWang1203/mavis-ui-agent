import time
import jiwer
import wave
import contextlib
from faster_whisper import WhisperModel

# 1. 实验数据配置
TEST_AUDIO = "/wyw/meeting_agent_workspace/my_agent/experiments/dataset/sample_meeting.wav"
GROUND_TRUTH = "欢迎大家来体验达摩院推出的语音识别模型"

def get_audio_duration(file_path):
    """严谨获取音频真实时长，用于计算学术指标 RTF"""
    with contextlib.closing(wave.open(file_path,'r')) as f:
        frames = f.getnframes()
        rate = f.getframerate()
        return frames / float(rate)

def calculate_metrics(transcription, inference_time, audio_duration):
    """计算 CER (越低越准) 和 RTF (越低越快)"""
    cer = jiwer.cer(GROUND_TRUTH, transcription)
    rtf = inference_time / audio_duration
    return cer, rtf

def run_faster_whisper():
    print("--- 🏁 启动参赛选手 1: Faster-Whisper (Small) ---")
    # 使用 CPU 和 int8 保证能在你当前的容器里绝对安全地跑通
    model = WhisperModel("tiny", device="cpu", compute_type="int8")
    
    audio_duration = get_audio_duration(TEST_AUDIO)
    print(f"▶️ 测试音频时长: {audio_duration:.2f} 秒")
    
    start_time = time.time()
    # 开始推理
    segments, info = model.transcribe(TEST_AUDIO, beam_size=5, language="zh")
    result_text = "".join([segment.text for segment in segments])
    end_time = time.time()
    
    inference_time = end_time - start_time
    cer, rtf = calculate_metrics(result_text, inference_time, audio_duration)
    
    print(f"📝 官方答案: {GROUND_TRUTH}")
    print(f"🤖 识别结果: {result_text}")
    print("-" * 40)
    print(f"📊 [Whisper 成绩单]")
    print(f"🎯 字符错误率 (CER): {cer:.4f} (越低越好，0表示全对)")
    print(f"⏱️ 纯推理耗时:       {inference_time:.2f} 秒")
    print(f"🚀 实时率 (RTF):     {rtf:.4f} (越低越好，<1表示比真实语速快)")
    print("-" * 40 + "\n")

if __name__ == "__main__":
    print("🚀 开始 ASR 速度与精度基准测试...\n")
    run_faster_whisper()
