# Preprocess Module

运行与测试说明：

1. 语法检查（在仓库根目录或者直接指定路径）：

```bash
python -m compileall /wyw/meeting_agent_workspace/my_agent/src/preprocess -q
```

2. 运行 Orchestrator（示例）：

```bash
python -m src.preprocess.orchestrator \
  --video data/demo_login.mp4 \
  --prompt "请根据这个视频中的草图和讲解，生成一个可运行的页面原型" \
  --output outputs/preprocess
```

3. 运行单元测试（在 workspace 根目录）：

```bash
pytest tests/preprocess -q
```

如果没有 `pytest`，请先安装测试依赖：

```bash
pip install -r requirements-test.txt
```

（`requirements-test.txt` 可以包含 `pytest`, `opencv-python`, `pydantic`）
