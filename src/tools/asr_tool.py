import json
import os
import subprocess
from pathlib import Path

from langchain_core.tools import tool
from src.utils.pipeline_trace import traced_stage, trace_event


if os.name != "nt":
    os.environ["PATH"] = f"/usr/bin:{os.environ.get('PATH', '')}"
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

model = None


def _workspace_root() -> Path:
    configured = os.getenv("MAVIS_WORKSPACE_ROOT")
    return Path(configured).expanduser().resolve() if configured else Path.cwd().resolve()


def _model_root(base_dir: Path) -> Path:
    configured = os.getenv("FUNASR_MODELS_DIR")
    return Path(configured).expanduser().resolve() if configured else base_dir / "data" / "models" / "iic"


def _format_time(milliseconds):
    seconds = milliseconds / 1000
    minutes, sec = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{sec:02d}"


def _run_ffmpeg_to_wav(audio_path: str, wav_path: str) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-i", audio_path, "-ar", "16000", "-ac", "1", wav_path],
        check=True,
        capture_output=True,
    )


def _resolve_funasr_models(model_root: Path) -> tuple[str, str, str, str]:
    asr_all_in_one = model_root / "speech_paraformer-large-vad-punc-spk_asr_nat-zh-cn"
    asr_online = model_root / "speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-online"
    if asr_all_in_one.is_dir():
        asr_path = str(asr_all_in_one)
    elif asr_online.is_dir():
        asr_path = str(asr_online)
    else:
        asr_path = "iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch"

    vad_local = model_root / "speech_fsmn_vad_zh-cn-16k-common-pytorch"
    punc_local = model_root / "punc_ct-transformer_zh-cn-common-vocab272727-pytorch"
    spk_local = model_root / "speech_campplus_sv_zh-cn_16k-common"

    vad_path = str(vad_local) if vad_local.is_dir() else "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch"
    punc_path = str(punc_local) if punc_local.is_dir() else "iic/punc_ct-transformer_zh-cn-common-vocab272727-pytorch"
    spk_path = str(spk_local) if spk_local.is_dir() else "iic/speech_campplus_sv_zh-cn_16k-common"
    return asr_path, vad_path, punc_path, spk_path


def _prepare_wav(audio_path: str) -> str:
    supported_formats = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg"}
    file_ext = Path(audio_path).suffix.lower()
    if file_ext not in supported_formats:
        raise ValueError(f"unsupported_audio_format:{file_ext}")

    if file_ext != ".wav":
        wav_path = str(Path(audio_path).with_suffix("")) + "_converted.wav"
        _run_ffmpeg_to_wav(audio_path, wav_path)
        return wav_path

    import wave

    with wave.open(audio_path, "rb") as wav:
        if wav.getframerate() != 16000 or wav.getnchannels() != 1:
            wav_path = str(Path(audio_path).with_suffix("")) + "_16k1ch.wav"
            _run_ffmpeg_to_wav(audio_path, wav_path)
            return wav_path

    return audio_path


def _parse_funasr_result(rec_result: dict) -> tuple[str, list[dict]]:
    final_lines: list[str] = []
    structured: list[dict] = []

    sentence_info = rec_result.get("sentence_info")
    if not sentence_info:
        text = rec_result.get("text", "")
        return text, [{"start_time": 0.0, "end_time": round(len(text) / 10.0, 2), "speaker": "Unknown", "text": text}]

    current_spk = None
    current_start_time = 0
    current_texts: list[str] = []

    for sentence in sentence_info:
        spk = sentence.get("spk", "Unknown")
        text = sentence.get("text", "").strip()
        if not text:
            continue

        start_raw = sentence.get("start", 0)
        end_raw = sentence.get("end", start_raw)
        start_sec = round(start_raw / 1000.0, 2) if start_raw > 1000 else round(float(start_raw), 2)
        end_sec = round(end_raw / 1000.0, 2) if end_raw > 1000 else round(float(end_raw), 2)
        structured.append({"start_time": start_sec, "end_time": end_sec, "speaker": f"Speaker {spk}", "text": text})

        if spk == current_spk:
            current_texts.append(text)
            continue

        if current_spk is not None:
            final_lines.append(f"[{_format_time(current_start_time)}] Speaker {current_spk}:\n{''.join(current_texts)}")
        current_spk = spk
        current_start_time = sentence.get("start", 0)
        current_texts = [text]

    if current_spk is not None:
        final_lines.append(f"[{_format_time(current_start_time)}] Speaker {current_spk}:\n{''.join(current_texts)}")

    return "\n\n".join(final_lines), structured


def _clear_model_after_error() -> None:
    global model
    if model is not None:
        del model
        model = None
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


@tool
@traced_stage('preprocess.asr_tool')
def asr_tool(audio_path: str) -> str:
    """Transcribe audio with FunASR and save both JSON and text transcripts."""
    global model
    try:
        if not os.path.isfile(audio_path):
            return f"[ASR failed: file does not exist: {audio_path}]"

        base_dir = _workspace_root()
        transcript_dir = base_dir / "outputs" / "transcripts"
        transcript_dir.mkdir(parents=True, exist_ok=True)

        model_root = _model_root(base_dir)
        asr_path, vad_path, punc_path, spk_path = _resolve_funasr_models(model_root)
        wav_path = _prepare_wav(audio_path)

        if model is None:
            from funasr import AutoModel

            model = AutoModel(
                model=asr_path,
                vad_model=vad_path,
                punc_model=punc_path,
                spk_model=spk_path,
                device=os.getenv("ASR_DEVICE", "cuda"),
                disable_update=True,
                disable_pbar=True,
                disable_log=True,
            )

        try:
            result = model.generate(input=wav_path, batch_size_s=60, is_final=True, sentence_timestamp=True)
        except Exception as exc:
            if "batch_size" not in str(exc):
                raise
            result = model.generate(input=wav_path, batch_size=1, is_final=True, sentence_timestamp=True)

        rec_result = result[0]
        trace_event('preprocess.asr_model_output',output=rec_result,
                    model_paths=[asr_path,vad_path,punc_path,spk_path])
        full_transcript, structured = _parse_funasr_result(rec_result)

        base_name = Path(audio_path).stem
        json_output_path = transcript_dir / f"{base_name}.json"
        txt_output_path = transcript_dir / f"{base_name}.normalized.txt"

        with open(json_output_path, "w", encoding="utf-8") as f:
            json.dump(structured, f, ensure_ascii=False, indent=2)
        with open(txt_output_path, "w", encoding="utf-8") as f:
            f.write(full_transcript)

        return (
            "ASR completed.\n"
            f"JSON transcript: {json_output_path}\n"
            f"Text transcript: {txt_output_path}\n"
            "Prefer the JSON transcript for downstream multimodal alignment."
        )

    except Exception as exc:
        _clear_model_after_error()
        return f"[ASR failed: internal error - {exc}]"
