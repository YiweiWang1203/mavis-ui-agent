from src.agents.agents import meeting_agent

# 1. 测试仅输入会议主题，生成会议大纲模板
def test_meeting_outline():
    print("\n=== 测试：仅输入会议主题，生成会议大纲模板 ===")
    state = {
        "messages": [
            {"role": "user", "content": "会议主题：人工智能能做什么"}
        ]
    }
    result = meeting_agent.invoke(state)
    for msg in result["messages"]:
        if hasattr(msg, 'role') and hasattr(msg, 'content'):
            print(f"{msg.role}: {msg.content}")
        elif isinstance(msg, dict):
            print(f"{msg['role']}: {msg['content']}")
        else:
            print(msg)

# 2. 测试输入会议音频，进行ASR和说话人分离
def test_meeting_audio():
    print("\n=== 测试：输入会议音频，ASR+说话人分离 ===")
    audio_path = "D:\Github\langmanus\langmanus\AI.m4a"
    user_message_audio = f"[AUDIO FILE]: {audio_path}"
    state_audio = {
        "messages": [
            {"role": "user", "content": user_message_audio}
        ]
    }
    result_audio = meeting_agent.invoke(state_audio)
    for msg in result_audio["messages"]:
        if hasattr(msg, 'role') and hasattr(msg, 'content'):
            print(f"{msg.role}: {msg.content}")
        elif isinstance(msg, dict):
            print(f"{msg['role']}: {msg['content']}")
        else:
            print(msg)

# 3. 测试输入会议主题+音频，完整流程（大纲模板+ASR+填充大纲+行动项）
def test_meeting_topic_and_audio():
    print("\n=== 测试：输入会议主题+音频，完整流程 ===")
    audio_path = "D:\Github\langmanus\langmanus\AI.m4a"
    state = {
        "messages": [
            {"role": "user", "content": "会议主题：人工智能能做什么"},
            {"role": "user", "content": f"[AUDIO FILE]: {audio_path}"}
        ]
    }
    result = meeting_agent.invoke(state)
    for msg in result["messages"]:
        if hasattr(msg, 'role') and hasattr(msg, 'content'):
            print(f"{msg.role}: {msg.content}")
        elif isinstance(msg, dict):
            print(f"{msg['role']}: {msg['content']}")
        else:
            print(msg)

if __name__ == "__main__":
    test_meeting_outline()
    test_meeting_audio()
    test_meeting_topic_and_audio()
    print("\n=== 流程测试结束 ===")
