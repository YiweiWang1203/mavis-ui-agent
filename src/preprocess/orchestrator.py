from __future__ import annotations
import argparse
import logging
from pathlib import Path
from .schemas import UserPreprocessInput
from .prompt_refiner import PromptRefiner
from .video_decomposer import VideoDecomposer
from .frame_selector import FinalSketchExtractor
from .sketch_rectifier import SketchRectifier
from .orientation_corrector import OrientationCorrector
from .platform_inferencer import PlatformRatioInferencer
from .sketch_normalizer import GeometryPreservingSketchNormalizer
from .package_builder import MultimodalPackageBuilder
from .utils import ensure_dir

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class PreAgentOrchestrator:
    def __init__(self, output_root: str = "outputs/preprocess"):
        self.output_root = Path(output_root)
        ensure_dir(self.output_root)
        self.prompt_refiner = PromptRefiner()
        self.video_decomposer = VideoDecomposer()
        self.frame_extractor = FinalSketchExtractor()
        self.rectifier = SketchRectifier()
        self.orienter = OrientationCorrector()
        self.inferencer = PlatformRatioInferencer()
        self.normalizer = GeometryPreservingSketchNormalizer()
        self.builder = MultimodalPackageBuilder(str(self.output_root / "metadata"))

    def run(self, input_data: UserPreprocessInput):
        out_dir = ensure_dir(Path(input_data.output_dir))
        errors = []
        warnings = []

        logger.info("Prompt refining started")
        # step 1: initial prompt refine
        pr_spec = self.prompt_refiner.refine(input_data.user_prompt)
        logger.info("Prompt refining completed")

        logger.info("Video decomposition started")
        # step 2: decompose video
        try:
            vres = self.video_decomposer.decompose(input_data.video_path, str(out_dir))
            logger.info("Video decomposition completed: %s", vres.video_path)
        except Exception as e:
            logger.error("video decompose failed: %s", e)
            raise

        # step 3: ASR (MVP: skip or mock)
        logger.info("ASR step started")
        transcript = ""
        if input_data.enable_asr:
            # placeholder for ASR
            transcript = "[mock transcript]"
        logger.info("ASR step completed")

        logger.info("Final sketch selection started")
        # step 4: select final sketch
        candidate_frames = vres.candidate_frame_paths
        timestamps = []
        # approximate timestamps from filenames
        import re
        for p in candidate_frames:
            m = re.search(r"_(\d+)s_", p)
            if m:
                try:
                    timestamps.append(float(m.group(1)))
                    continue
                except Exception:
                    pass
            timestamps.append(0.0)

        final_result = self.frame_extractor.select_final_sketch(candidate_frames, timestamps, str(out_dir / "frames"))

        logger.info("Final sketch selection completed: %s", final_result.selected_frame_path)

        logger.info("Sketch rectification started")
        # step 5: rectification
        rect_res = self.rectifier.rectify(final_result.selected_frame_path, str(out_dir / "sketches"))
        logger.info("Sketch rectification completed: %s", rect_res.rectified_sketch_path)

        logger.info("Orientation correction started")
        # step 5.5: orientation correction (default enabled)
        try:
            orientation_result = self.orienter.correct(
                rect_res.rectified_sketch_path or final_result.selected_frame_path,
                str(out_dir),
                rotation_degrees=getattr(input_data, "rotate_degrees", 180),
                enabled=not getattr(input_data, "disable_orientation_correction", False),
            )
            logger.info("Orientation correction completed: %s", orientation_result.corrected_sketch_path)
        except Exception as e:
            logger.error("Orientation correction failed: %s", e)
            raise

        logger.info("Second prompt refining started")
        # step 6: second prompt refine with transcript
        pr_spec2 = self.prompt_refiner.refine(input_data.user_prompt, transcript_text=transcript)
        logger.info("Second prompt refining completed")

        logger.info("Platform inference started")
        # step 7: platform inference
        platform_res = self.inferencer.infer(input_data.user_prompt, transcript, rect_res.rectified_sketch_path or final_result.selected_frame_path)
        logger.info("Platform inference completed: %s %s", platform_res.platform, platform_res.target_ratio)

        logger.info("Sketch normalization started")
        # step 8: normalization - use orientation-corrected sketch if available
        norm_input = (orientation_result.corrected_sketch_path if orientation_result and orientation_result.corrected_sketch_path else rect_res.rectified_sketch_path or final_result.selected_frame_path)
        norm_res = self.normalizer.normalize(norm_input, platform_res, str(out_dir / "normalized"), input_after_orientation_correction=bool(orientation_result and orientation_result.corrected_sketch_path))
        logger.info("Sketch normalization completed: %s", norm_res.normalized_sketch_path)

        # handle audio warning
        if not vres.audio_path:
            warn = "ffmpeg is not available or audio extraction failed; audio_path is null"
            warnings.append(warn)
            logger.warning(warn)

        # ensure transcript_text is string
        transcript = transcript or ""

        logger.info("Package building started")
        # step 9: build package
        pkg = self.builder.build(
            input_video=input_data.video_path,
            raw_user_prompt=input_data.user_prompt,
            optimized_prompt_spec=pr_spec2,
            audio_path=vres.audio_path,
            transcript_text=transcript,
            candidate_frames=candidate_frames,
            selected_sketch_path=final_result.selected_frame_path,
            rectified_sketch_path=rect_res.rectified_sketch_path,
            normalized_sketch_path=norm_res.normalized_sketch_path,
            platform_hint=platform_res,
            preprocess_metadata={"video_meta": vres.metadata},
            errors=errors,
            warnings=warnings,
            orientation_result=orientation_result,
        )

        logger.info("Package building completed")

        return pkg


def main():
    parser = argparse.ArgumentParser(description="Pre-Agent Orchestrator CLI")
    parser.add_argument("--video", required=True, help="path to video file")
    parser.add_argument("--prompt", required=True, help="user prompt")
    parser.add_argument("--output", default="outputs/preprocess", help="output dir")
    parser.add_argument("--rotate-degrees", type=int, choices=[0, 90, 180, 270], default=180, help="rotation degrees to correct orientation (default 180)")
    parser.add_argument("--disable-orientation-correction", action="store_true", help="disable orientation correction step")
    args = parser.parse_args()
    inp = UserPreprocessInput(user_prompt=args.prompt, video_path=args.video, output_dir=args.output, rotate_degrees=args.rotate_degrees, disable_orientation_correction=args.disable_orientation_correction)
    orch = PreAgentOrchestrator(output_root=args.output)
    pkg = orch.run(inp)
    print("Package created:", pkg)


if __name__ == "__main__":
    main()
