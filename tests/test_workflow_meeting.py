from src.workflow import run_agent_workflow

if __name__ == "__main__":
    # 测试输入会议主题+音频，模拟真实用户输入
    audio_path = "D:/Github/langmanus/langmanus/AI.m4a"  # 替换为你的实际音频文件路径
    user_message = f"会议主题：人工智能能做什么\n[AUDIO FILE]: {audio_path}"
    messages = [
        {"role": "user", "content": user_message}
    ]
    result = run_agent_workflow(messages, debug=True)
    print("=== run_agent_workflow 输出 ===")
    for msg in result["messages"]:
        if hasattr(msg, "content"):
            print(msg.content)
        elif isinstance(msg, dict):
            print(msg.get("content", msg))
        else:
            print(msg)
