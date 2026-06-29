import os

def test_placeholder_vision():
    # 轻量级占位测试，验证 visual_raw 目录存在
    assert os.path.isdir('data/visual_raw')
