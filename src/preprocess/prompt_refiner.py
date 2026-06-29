from __future__ import annotations
from typing import Optional
from .schemas import OptimizedPromptSpec
import logging

logger = logging.getLogger(__name__)


class PromptRefiner:
    def __init__(self, enable_llm: bool = False):
        self.enable_llm = enable_llm

    def refine(self, user_prompt: str, transcript_text: str = "", visual_hint: str = "") -> OptimizedPromptSpec:
        # Rule-based MVP refiner
        inferred_task = "ui_prototype_generation"
        expected_outputs = [
            "UI component extraction",
            "structured UI-State JSON",
            "executable UI prototype",
            "mock RPA or business logic",
        ]
        constraints = [
            "preserve sketch layout intent",
            "use speech to resolve visual ambiguity",
            "use visual sketch to correct speech ambiguity",
            "generate runnable code",
            "keep intermediate UI-State explicit",
        ]

        uncertainties = []
        evidence = []
        low = 0.6
        high = 0.95

        # simple keyword scanning for platform evidence
        prompt_lower = (user_prompt or "").lower()
        if any(k in prompt_lower for k in ["手机", "移动端", "小程序", "app", "h5"]):
            evidence.append("mobile")
        if any(k in prompt_lower for k in ["网页端", "pc", "后台", "管理系统", "dashboard"]):
            evidence.append("desktop")

        optimized = f"Task: {inferred_task}. User: {user_prompt}."
        if transcript_text:
            optimized += f" Transcript: {transcript_text}."

        confidence = high if evidence else low

        spec = OptimizedPromptSpec(
            raw_prompt=user_prompt,
            optimized_prompt=optimized,
            user_goal=user_prompt,
            expected_outputs=expected_outputs,
            constraints=constraints,
            uncertainties=uncertainties,
            inferred_task_type=inferred_task,
            confidence=confidence,
        )

        if self.enable_llm:
            try:
                llm_spec = self._call_llm_refiner(user_prompt, transcript_text, visual_hint)
                # merge if returned
                if llm_spec and isinstance(llm_spec, dict):
                    for k, v in llm_spec.items():
                        if hasattr(spec, k):
                            setattr(spec, k, v)
            except Exception as e:
                logger.warning("LLM refiner failed: %s", e)

        return spec

    def _call_llm_refiner(self, user_prompt: str, transcript_text: str = "", visual_hint: str = "") -> Optional[dict]:
        # Placeholder for LLM integration
        raise NotImplementedError("LLM refiner not implemented in MVP")
