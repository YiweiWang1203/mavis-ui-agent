import os
import sys
import logging
from dotenv import load_dotenv

# 获取当前文件所在目录 (tests)
current_dir = os.path.dirname(os.path.abspath(__file__))
# 往上一级，拿到真正的项目根目录 (my_agent)
project_root = os.path.abspath(os.path.join(current_dir, ".."))

# 把根目录塞进 Python 的搜索口袋里
if project_root not in sys.path:
    sys.path.insert(0, project_root)

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

from src.graph.builder import build_graph
from src.config import TEAM_MEMBERS

def run_smoke_test():
    print("\n" + "="*50)
    print("🚀 启动多模态 Agent 冒烟测试 (Smoke Test)")
    print("="*50 + "\n")
    
    graph = build_graph()
    
    # 构造假的用户输入
    fake_messages = [{
        "role": "user", 
        "content": (
            "这是一次系统测试。请你调用 meeting_agent 听一下这段录音，并总结出录音里说了什么。"
            "就算录音内容和 UI 设计无关也没关系，原样提取核心意思即可。\n"
            "[AUDIO FILE]: /wyw/meeting_agent_workspace/my_agent/data/audio_raw/R8001_M8004_N_SPK8013.wav \n"
            "[IMAGE]: mock_sketch.jpg"
        )
    }]
    
    # 触发 LangGraph 工作流
    result = graph.invoke({
        "TEAM_MEMBERS": TEAM_MEMBERS,
        "messages": fake_messages,
        # 传入初始状态
        "voice_intent": None,
        "vision_elements": None,
        "ui_state_json": None
    })
    
    print("\n" + "="*50)
    print("✅ 测试结束！检查全局档案袋 (State) 里的最终资产：")
    print("="*50)
    print(f"🎙️ 语音意图: {result.get('voice_intent')}")
    print(f"👁️ 视觉坐标: {result.get('vision_elements')}")
    print(f"🧠 UI 契约:  {result.get('ui_state_json')}")
    print(f"📋 执行步数: {result.get('current_step')}")
    
if __name__ == "__main__":
    run_smoke_test()