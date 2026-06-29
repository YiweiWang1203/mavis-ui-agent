from src.preprocess.platform_inferencer import PlatformRatioInferencer


def test_platform_infer_mobile():
    inf = PlatformRatioInferencer()
    res = inf.infer("请生成一个手机端 App 登录页面", "", "")
    assert res.platform == "mobile"
    assert res.target_ratio == "9:16"


def test_platform_infer_desktop():
    inf = PlatformRatioInferencer()
    res = inf.infer("请生成一个后台管理系统 dashboard", "", "")
    assert res.platform == "desktop"
    assert res.target_ratio in ["16:9", "16:10"] or res.target_ratio == "16:9"
