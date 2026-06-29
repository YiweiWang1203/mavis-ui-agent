from src.agents.agents import meeting_agent
from src.tools.asr_tool import asr_tool

if __name__ == "__main__":
    # 直接测试 meeting_agent 是否 function call asr_tool
    audio_path = "D:/Github/langmanus/langmanus/AI.m4a"  # 替换为你的实际音频文件路径
    user_message = f"会议主题：人工智能能做什么\n[AUDIO FILE]: {audio_path}"
    state = {
        "messages": [
            {"role": "user", "content": user_message}
        ]
    }
    print("=== meeting_agent.invoke 输出 ===")
    result = meeting_agent.invoke(state)
    for msg in result["messages"]:
        if hasattr(msg, "content"):
            print(msg.content)
        elif isinstance(msg, dict):
            print(msg.get("content", msg))
        else:
            print(msg)

    print("\n=== 直接调用 asr_tool 输出 ===")
    asr_result = asr_tool(audio_path)
    print(asr_result)

    print("\n请人工比对 meeting_agent 的 <ASR> 内容与 asr_tool 输出是否一致，判断是否 function call 成功！")
