from my_agent.src import read_file_tool
import os

# 找一个之前 ASR 生成的文件路径，或者随便指定一个现有的 txt
test_file = "/wyw/meeting_agent_workspace/my_agent/outputs/transcripts/your_file_name_diarization.txt" # 替换成你实际的文件名

if os.path.exists(test_file):
    print("🔍 正在测试读取工具...")
    content = read_file_tool.invoke({"file_path": test_file, "max_chars": 500})
    print("-" * 30)
    print(content)
    print("-" * 30)
else:
    print(f"❌ 未找到测试文件: {test_file}，请检查路径是否正确。")