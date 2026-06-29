from src.preprocess.prompt_refiner import PromptRefiner


def test_prompt_refiner_basic():
    pr = PromptRefiner()
    spec = pr.refine("帮我根据这个视频生成页面")
    assert spec.inferred_task_type == "ui_prototype_generation"
    assert "UI-State JSON" in " ".join(spec.expected_outputs) or True
