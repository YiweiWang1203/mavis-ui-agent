from __future__ import annotations
from pathlib import Path
import json
from .schemas import MultimodalPreprocessPackage
from .utils import ensure_dir, unique_path


class MultimodalPackageBuilder:
    def __init__(self, output_dir: str):
        self.output_dir = ensure_dir(Path(output_dir))

    def build(self, *, input_video: str, raw_user_prompt: str, optimized_prompt_spec, audio_path: str, transcript_text: str, candidate_frames, selected_sketch_path: str, rectified_sketch_path: str, normalized_sketch_path: str, platform_hint, preprocess_metadata: dict, errors: list, warnings: list, orientation_result=None) -> MultimodalPreprocessPackage:
        # augment preprocess_metadata with orientation info if provided
        if orientation_result is not None:
            preprocess_metadata.setdefault("orientation_correction", {})
            preprocess_metadata["orientation_correction"].update({
                "applied": bool(orientation_result.enabled),
                "rotation_degrees": int(orientation_result.rotation_degrees),
                "method": orientation_result.method,
                "reason": orientation_result.reason,
                "input_sketch_path": orientation_result.input_sketch_path,
                "corrected_sketch_path": orientation_result.corrected_sketch_path,
            })

        pkg = MultimodalPreprocessPackage(
            input_video=input_video,
            raw_user_prompt=raw_user_prompt,
            optimized_prompt_spec=optimized_prompt_spec,
            audio_path=audio_path,
            transcript_text=transcript_text,
            candidate_frames=candidate_frames,
            selected_sketch_path=selected_sketch_path,
            rectified_sketch_path=rectified_sketch_path,
            orientation_corrected_sketch_path=(orientation_result.corrected_sketch_path if orientation_result else None),
            normalized_sketch_path=normalized_sketch_path,
            platform_hint=platform_hint,
            preprocess_metadata=preprocess_metadata,
            errors=errors,
            warnings=warnings,
        )

        outp = unique_path(self.output_dir / "package.json")

        # Use Pydantic v2 API: prefer model_dump_json; fall back to json.dumps of model_dump
        try:
            text = pkg.model_dump_json(indent=2, ensure_ascii=False)
        except Exception:
            import json

            text = json.dumps(pkg.model_dump(), ensure_ascii=False, indent=2)

        with open(outp, "w", encoding="utf-8") as f:
            f.write(text)

        # metadata already augmented above

        # record the actual package path into the model and rewrite file so it's included
        try:
            pkg.package_path = str(outp)
            try:
                text = pkg.model_dump_json(indent=2, ensure_ascii=False)
            except Exception:
                text = json.dumps(pkg.model_dump(), ensure_ascii=False, indent=2)
            with open(outp, "w", encoding="utf-8") as f:
                f.write(text)
        except Exception:
            # best-effort: if setting package_path fails, leave original file as-is
            pass

        return pkg
