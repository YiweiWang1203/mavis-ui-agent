import os
import json
from openai import OpenAI
from dotenv import load_dotenv

# 自动加载项目根目录的 .env 文件
load_dotenv()

# 初始化兼容 OpenAI 的客户端
client = OpenAI(
    api_key=os.getenv("SILICONFLOW_API_KEY"),
    base_url=os.getenv("SILICONFLOW_BASE_URL", "[https://api.siliconflow.cn/v1](https://api.siliconflow.cn/v1)")
)

def read_ui_architect_prompt():
    """读取 UI Architect 的系统提示词"""
    prompt_path = os.path.join(os.path.dirname(__file__), "../prompts/ui_architect.md")
    try:
        with open(prompt_path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "你是一位具备深度洞察力的 UI 架构师。你的原则是：忠于草图，合理解构。请将用户意图和视觉坐标融合为合法的 UI-State JSON。"

def generate_ui_state(user_intent: str, vision_elements: dict) -> dict:
    """
    大脑调度器：融合用户意图与视觉坐标，生成最终的 UI-State JSON
    """
    system_prompt = read_ui_architect_prompt()
    
    # 构造融合了听觉(意图)与视觉(坐标)的用户输入
    user_content = f"""
    【User Intent (用户意图)】:
    {user_intent}
    
    【Vision Elements (视觉空间数据)】:
    {json.dumps(vision_elements, ensure_ascii=False, indent=2)}
    
    请输出最终融合后的 UI-State JSON：
    """

    try:
        print("🧠 Planner 正在思考，融合业务逻辑与视觉坐标...")
        # 推荐使用逻辑推理能力较强的模型（这里默认读取生产环境模型，如果没有则用调试模型）
        planner_model = os.getenv("CODER_PROD_MODEL", os.getenv("CODER_MODEL", "deepseek-ai/DeepSeek-V3"))
        
        response = client.chat.completions.create(
            model=planner_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            temperature=0.3, # Planner 需要较高的稳定性和逻辑一致性
            response_format={"type": "json_object"} # 强制输出纯净的 JSON
        )
        
        raw_json_str = response.choices[0].message.content
        return json.loads(raw_json_str)
        
    except json.JSONDecodeError as e:
        print(f"❌ Planner 输出的 JSON 解析失败: {e}")
        return {"error": "JSON_PARSE_ERROR"}
    except Exception as e:
        print(f"❌ Planner 调度失败: {e}")
        return {"error": str(e)}

# ====== 本地独立测试入口 ======
if __name__ == "__main__":
    # 模拟从 ASR 获取的用户意图
    mock_user_intent = "帮我弄一个差旅报销单，上面输入姓名和金额，下面是一个大大的提交按钮用于触发审批流。"
    
    # 模拟从 Vision Tool 获取的坐标数据
    mock_vision_data = {
        "elements": [
            {"type": "input_text", "label": "未知输入框1", "spatial_info": {"bbox": [0.1, 0.1, 0.4, 0.15]}},
            {"type": "input_text", "label": "未知输入框2", "spatial_info": {"bbox": [0.1, 0.2, 0.4, 0.25]}},
            {"type": "button", "label": "按钮", "spatial_info": {"bbox": [0.3, 0.8, 0.7, 0.9]}}
        ]
    }
    
    result = generate_ui_state(mock_user_intent, mock_vision_data)
    print("\n🎉 Planner 融合生成的最终 UI-State JSON:\n")
    print(json.dumps(result, indent=2, ensure_ascii=False))