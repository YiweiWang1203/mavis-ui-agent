import os
import json
from openai import OpenAI
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

client = OpenAI(
    api_key=os.getenv("SILICONFLOW_API_KEY"),
    base_url=os.getenv("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1")
)

def read_planner_prompt():
    """读取全局总指挥的提示词"""
    prompt_path = os.path.join(os.path.dirname(__file__), "../prompts/planner.md")
    try:
        with open(prompt_path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "你是一个调度系统，请输出 JSON 计划。"

def generate_execution_plan(user_input: str) -> dict:
    """
    接收用户最原始的输入（包含文本、图片路径、音频路径等），输出 Agent 协同步骤
    """
    system_prompt = read_planner_prompt()
    
    try:
        print("🧭 Planner (总管家) 正在分析任务，制定多智能体协同计划...")
        # Planner 负责全局统筹，必须用智商最高的模型 (DeepSeek-V3)
        planner_model = os.getenv("CODER_PROD_MODEL", "deepseek-ai/DeepSeek-V3")
        
        response = client.chat.completions.create(
            model=planner_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_input}
            ],
            temperature=0.1, # 极低的温度，保证 JSON 格式和步骤的绝对严谨
            response_format={"type": "json_object"}
        )
        
        raw_json_str = response.choices[0].message.content
        return json.loads(raw_json_str)
        
    except json.JSONDecodeError as e:
        print(f"❌ Planner 计划解析失败，输出的不是合法 JSON: {e}")
        return {"error": "JSON_PARSE_ERROR"}
    except Exception as e:
        print(f"❌ Planner 调度失败: {e}")
        return {"error": str(e)}

# ====== 本地独立测试入口 ======
if __name__ == "__main__":
    # 模拟用户的原始多模态输入
    mock_user_input = "帮我把这张白板草图做成前端页面，具体要求在录音里。\n[AUDIO FILE]: intent.wav \n[IMAGE]: sketch.jpg"
    
    plan_result = generate_execution_plan(mock_user_input)
    print("\n📋 Planner 生成的执行步骤 (Execution Plan):\n")
    print(json.dumps(plan_result, indent=2, ensure_ascii=False))