from src.agents.agents import sa2va_agent
from langchain_core.messages import HumanMessage  # 加这一行

if __name__ == "__main__":
    # 直接测试指定帧文件夹和问题，便于复现和排查
    video_folder = r"D:\Github\SegAnyGAussians\data\360_v2\garden\input"  # 修改为你的实际帧文件夹
    question = "<image>where is the table？"
    state = {
        "messages": [
            HumanMessage(content=f"{question}\nVideo frame folder: {video_folder}")
        ]
    }
    result = sa2va_agent.invoke(state)
    print("=== sa2va_agent 视觉问答输出 ===")
    print(result)
