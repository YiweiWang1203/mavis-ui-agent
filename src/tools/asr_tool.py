import os
import subprocess
import json
from datetime import timedelta
from langchain_core.tools import tool

# 1. 强制系统 ffmpeg
os.environ["PATH"] = f"/usr/bin:{os.environ.get('PATH', '')}"
# 2. 强制显存碎片优化 (防止长音频 OOM)
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"

model = None

def format_time(milliseconds):
    """将毫秒转换为 0:00:00 格式"""
    seconds = milliseconds / 1000
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}"

@tool
def asr_tool(audio_path: str) -> str:
    """使用 FunASR 进行ASR转写和说话人分离。此工具会将长文本保存到本地文件，并仅返回文件路径和预览给LLM，防止撑爆大模型上下文。"""
    global model
    try:
        if not os.path.isfile(audio_path):
            return f"[ASR识别失败: 文件不存在 {audio_path}]"

        BASE_DIR = "/wyw/meeting_agent_workspace/my_agent"
        TRANSCRIPT_DIR = os.path.join(BASE_DIR, "outputs/transcripts")
        os.makedirs(TRANSCRIPT_DIR, exist_ok=True)

        # 👉 使用官方推荐的 FunASR 组合方式：主 ASR + 可选的 vad/punc/spk 模型
        BASE_MODELS_DIR = os.path.join(BASE_DIR, "data/models/iic")
        # 优先使用本地模型目录（如果存在），否则使用 ModelScope ID 由 funasr 底层下载
        # 优先使用本地的全家桶目录（若存在），可避免网络下载和 404
        asr_candidate_allinone = os.path.join(BASE_MODELS_DIR, "speech_paraformer-large-vad-punc-spk_asr_nat-zh-cn")
        asr_candidate_online = os.path.join(BASE_MODELS_DIR, "speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-online")
        if os.path.isdir(asr_candidate_allinone):
            asr_path = asr_candidate_allinone
        elif os.path.isdir(asr_candidate_online):
            asr_path = asr_candidate_online
        else:
            asr_path = "iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch"

        vad_candidate = os.path.join(BASE_MODELS_DIR, "speech_fsmn_vad_zh-cn-16k-common-pytorch")
        vad_path = vad_candidate if os.path.isdir(vad_candidate) else "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch"

        punc_candidate = os.path.join(BASE_MODELS_DIR, "punc_ct-transformer_zh-cn-common-vocab272727-pytorch")
        punc_path = punc_candidate if os.path.isdir(punc_candidate) else "iic/punc_ct-transformer_zh-cn-common-vocab272727-pytorch"

        spk_candidate = os.path.join(BASE_MODELS_DIR, "speech_campplus_sv_zh-cn_16k-common")
        spk_path = spk_candidate if os.path.isdir(spk_candidate) else "iic/speech_campplus_sv_zh-cn_16k-common"

        # --- 音频格式校验与转换 ---
        wav_path = audio_path
        supported_formats = ['.wav', '.mp3', '.m4a', '.aac', '.flac', '.ogg']
        file_ext = os.path.splitext(audio_path)[1].lower()
        
        if file_ext not in supported_formats:
            return f"[ASR识别失败: 不支持的音频格式 {file_ext}]"
        
        if file_ext != '.wav':
            base_name = os.path.splitext(audio_path)[0]
            wav_path = f"{base_name}_converted.wav"
            subprocess.run(["ffmpeg", "-y", "-i", audio_path, "-ar", "16000", "-ac", "1", wav_path], check=True, capture_output=True)
        else:
            import wave
            with wave.open(audio_path, 'rb') as wf:
                if wf.getframerate() != 16000 or wf.getnchannels() != 1:
                    base_name = os.path.splitext(audio_path)[0]
                    wav_path = f"{base_name}_16k1ch.wav"
                    subprocess.run(["ffmpeg", "-y", "-i", audio_path, "-ar", "16000", "-ac", "1", wav_path], check=True, capture_output=True)

        # --- 模型加载 ---
        if model is None:
            from funasr import AutoModel
            # 官方推荐的合体版调用方式：主模型 + vad/punc/spk（FunASR 会在内部串联）
            model = AutoModel(
                model=asr_path,
                vad_model=vad_path,
                punc_model=punc_path,
                spk_model=spk_path,
                device="cuda",
                disable_update=True,
                disable_pbar=True,
                disable_log=True
            )

        # --- 执行推理 (优先使用时间窗参数; 若模型要求单样本批次则回退到 batch_size=1) ---
        try:
            res = model.generate(input=wav_path, batch_size_s=60, is_final=True, sentence_timestamp=True)
        except Exception as gen_e:
            err_msg = str(gen_e)
            if 'batch_size must be set 1' in err_msg or 'batch_size' in err_msg:
                # 回退为批次 1 的推理（兼容某些 speaker/seg 模型要求）
                res = model.generate(input=wav_path, batch_size=1, is_final=True, sentence_timestamp=True)
            else:
                raise
        
        # --- 结果解析：合并连续说话人 ---
        rec_result = res[0]
        final_lines = []
        
        if 'sentence_info' in rec_result:
            current_spk = None
            current_start_time = 0
            current_texts = []

            for sentence in rec_result['sentence_info']:
                spk = sentence.get("spk", "Unknown")
                text = sentence.get("text", "").strip()
                if not text:
                    continue

                if spk == current_spk:
                    # 如果说话人没变，把内容拼接到当前段落
                    current_texts.append(text)
                else:
                    # 如果换人了，先把上一个人的完整段落保存下来
                    if current_spk is not None:
                        timestamp = format_time(current_start_time)
                        merged_text = "".join(current_texts)
                        final_lines.append(f"[{timestamp}] Speaker {current_spk}:\n{merged_text}")
                    
                    # 开始记录新说话人的段落
                    current_spk = spk
                    current_start_time = sentence.get("start", 0)
                    current_texts = [text]

            # 循环结束，别忘了把最后一个人说的话存进去
            if current_spk is not None:
                timestamp = format_time(current_start_time)
                merged_text = "".join(current_texts)
                final_lines.append(f"[{timestamp}] Speaker {current_spk}:\n{merged_text}")
        else:
            final_lines.append("未检测到说话人分离信息。\n" + rec_result.get('text', ''))

        full_transcript = "\n\n".join(final_lines)

        # --- 写入结构化 JSON 与人类可读 TXT（双轨输出） ---
        base_name = os.path.basename(audio_path).replace('.wav', '')
        json_output_path = os.path.join(TRANSCRIPT_DIR, f"{base_name}.json")
        txt_output_path = os.path.join(TRANSCRIPT_DIR, f"{base_name}.normalized.txt")

        structured = []
        txt_lines = []

        if 'sentence_info' in rec_result:
            for sentence in rec_result['sentence_info']:
                start_raw = sentence.get('start', 0)
                end_raw = sentence.get('end', start_raw)
                # FunASR 有时返回 ms，有时返回 s：若数值大于 1000 则视为毫秒
                start_sec = round(start_raw / 1000.0, 2) if start_raw > 1000 else round(float(start_raw), 2)
                end_sec = round(end_raw / 1000.0, 2) if end_raw > 1000 else round(float(end_raw), 2)

                spk = f"Speaker {sentence.get('spk', 'Unknown')}"
                text = sentence.get('text', '').strip()

                structured.append({
                    'start_time': start_sec,
                    'end_time': end_sec,
                    'speaker': spk,
                    'text': text
                })

                txt_lines.append(f"[{start_sec:.2f}s - {end_sec:.2f}s] {spk}:\n{text}\n")
        else:
            # 退化：如果没有 sentence_info，就把合并的 full_transcript 写入一个单条记录
            structured.append({
                'start_time': 0.0,
                'end_time': round(len(full_transcript)/10.0,2),
                'speaker': 'Unknown',
                'text': full_transcript
            })
            txt_lines.append(full_transcript)

        with open(json_output_path, 'w', encoding='utf-8') as f:
            json.dump(structured, f, ensure_ascii=False, indent=2)

        with open(txt_output_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(txt_lines))

        return (
            f"✅ ASR 语音识别与角色分离已完成！\n"
            f"📁 机器可读（JSON）已保存至: {json_output_path}\n"
            f"📄 人类可读（TXT）已保存至: {txt_output_path}\n"
            f"💡 强烈提示：请优先读取 `.json` 文件以获取包含精确秒数的时空坐标，用于后续跨模态对齐与业务抽取。"
        )

    except Exception as e:
        # --- 显存强制清洗机制 (防止加载失败产生的幽灵显存撑爆机器) ---
        import torch
        #global model
        if model is not None:
            del model
            model = None
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            
        return f"[ASR识别失败: 内部执行出错 - {str(e)}]"