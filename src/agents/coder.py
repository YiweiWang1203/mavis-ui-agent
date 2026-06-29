import os
from dotenv import load_dotenv
load_dotenv()  # 自动寻找并加载项目根目录的 .env 文件
import json
from openai import OpenAI
import time
import logging
from pathlib import Path
from src.agents.utils.path_manager import HTML_OUTPUT_DIR

# 从环境变量读取 API Key / base_url / coder 模型配置（参见 .env）
SILICONFLOW_API_KEY = os.getenv("SILICONFLOW_API_KEY") or os.getenv("OPENAI_API_KEY")
SILICONFLOW_BASE_URL = os.getenv("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1")
# 调试阶段默认模型（低成本）
DEFAULT_CODER_MODEL = os.getenv("CODER_MODEL", "Qwen/Qwen2.5-Coder-32B")
# 生产/最终渲染模型（可切换到此模型以获得更漂亮的 UI）
PROD_CODER_MODEL = os.getenv("CODER_PROD_MODEL", os.getenv("CODER_PROD_MODEL", "deepseek-ai/DeepSeek-V3"))

# 支持 DeepSeek 使用单独的 key（可选），否则回退到 SILICONFLOW_API_KEY
CODEER_API_KEY = os.getenv("DEEPSEEK_API_KEY") or SILICONFLOW_API_KEY

if CODEER_API_KEY:
    client = OpenAI(api_key=CODEER_API_KEY, base_url=SILICONFLOW_BASE_URL)
else:
    client = None
    print("⚠️ Coder: 未检测到 API Key（DEEPSEEK_API_KEY 或 SILICONFLOW_API_KEY），代码生成调用将被跳过。")

def read_coder_prompt():
    """读取我们刚刚重写的 coder.md 提示词"""
    prompt_path = os.path.join(os.path.dirname(__file__), "../prompts/coder.md")
    try:
        with open(prompt_path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "你是一个优秀的前端工程师，请根据 JSON 生成代码。"

def generate_frontend_code(ui_state_json: dict, audit_logger=None) -> str:
    """
    核心执行器：将 UI-State JSON 发送给 DeepSeek-V3 生成前端代码
    """
    system_prompt = read_coder_prompt()
    user_content = f"请根据以下 UI-State JSON 生成前端代码：\n\n{json.dumps(ui_state_json, ensure_ascii=False, indent=2)}"

    # 允许通过环境变量选择模型：默认使用调试模型（低成本），生产时可改为 deepseek
    model_to_use = os.getenv("CODER_MODEL", DEFAULT_CODER_MODEL)

    if client is None:
        print("❌ Coder: 未配置 API Key，无法调用远端模型生成代码。请在 .env 中设置 SILICONFLOW_API_KEY 或 DEEPSEEK_API_KEY 。")
        return ""

    try:
        print(f"🚀 正在使用模型 {model_to_use} 生成前端代码...")
        response = client.chat.completions.create(
            model=model_to_use,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            temperature=0.2
        )

        code_str = response.choices[0].message.content

        # Audit: record llm call if logger provided
        try:
            if audit_logger:
                audit_logger.log_llm_call('coder', model_to_use, system_prompt, user_content, None, code_str, {'note': 'coder generation'})
        except Exception:
            pass

        # 保存生成的代码为文件资产，并返回文件绝对路径（如果保存成功）
        saved_path = None
        try:
            from datetime import datetime
            # 构造人类可读的时间戳，例如: 20260528_112333
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            # 🌟 修复硬编码：使用通用的命名前缀
            filename = f"html_generated_{timestamp}.html"
            file_path = HTML_OUTPUT_DIR / filename
            # 确保目录存在（path_manager 已经创建，但再保一手）
            file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(code_str)
            saved_path = str(file_path.resolve())
            logging.getLogger(__name__).info(f"✅ HTML 资产已保存至: {saved_path}")
        except Exception as e:
            logging.getLogger(__name__).error(f"❌ HTML 资产保存失败: {e}")

        # 返回包含代码与文件路径的字典（file_path 可能为 None）
        return {"code": code_str, "file_path": saved_path}

    except Exception as e:
        print(f"❌ 代码生成失败: {e}")
        return ""

# ====== 本地独立测试入口 ======
if __name__ == "__main__":
    # 加载你在 vision 阶段生成的 example JSON
    test_json_path = "outputs/ui_states/example_R8001_M8004_MS801.json"
    
    if os.path.exists(test_json_path):
        with open(test_json_path, "r", encoding="utf-8") as f:
            mock_ui_state = json.load(f)
            
        result = generate_frontend_code(mock_ui_state)
        print("\n🎉 DeepSeek-V3 生成的最终代码:\n")
        # result 现在是一个字典，打印代码与保存路径
        if isinstance(result, dict):
            print(result.get("code", ""))
            print("\nSaved to:", result.get("file_path"))
        else:
            print(result)
    else:
        print(f"⚠️ 找不到测试文件: {test_json_path}")