"""Real FunASR adapter, using existing local model configuration only."""
from pathlib import Path
import json


def transcribe_audio(audio_path: str, output_dir: str) -> str:
    if not audio_path or not Path(audio_path).is_file():
        raise ValueError("ASR requires an extracted audio file")
    from src.tools.asr_tool import (
        _model_root, _workspace_root, _resolve_funasr_models, _prepare_wav,
    )
    import os
    explicit_config = os.getenv("MAVIS_ASR_MODEL_CONFIG")
    if explicit_config:
        from src.utils.local_asr_model_config import resolve_verified_models
        model_paths = resolve_verified_models(explicit_config)
    else:
        model_paths = _resolve_funasr_models(_model_root(_workspace_root()))
    if not all(Path(path).is_dir() for path in model_paths):
        raise RuntimeError("ASR local model set incomplete; automatic downloads disabled")
    from funasr import AutoModel
    import os
    model = AutoModel(model=model_paths[0], vad_model=model_paths[1],
                      punc_model=model_paths[2], spk_model=model_paths[3],
                      device=os.getenv("ASR_DEVICE", "cuda"), disable_update=True,
                      disable_pbar=True, disable_log=True)
    result = model.generate(input=_prepare_wav(audio_path), batch_size_s=60,
                            is_final=True, sentence_timestamp=True, pred_timestamp=True)
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    # Preserve raw ASR evidence; do not claim verified temporal alignment.
    (target / "asr_raw.json").write_text(json.dumps({
        "source": "funasr", "model_paths": model_paths,
        "timestamps_verified": False, "result": result,
    }, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    text = result[0].get("text", "").strip() if result else ""
    if not text:
        raise ValueError("ASR returned empty text")
    (target / "transcript.txt").write_text(text, encoding="utf-8")
    return text
