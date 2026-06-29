import sys
import os
import argparse
from dotenv import load_dotenv

# 加载环境变量并配置导入路径
load_dotenv("/wyw/meeting_agent_workspace/my_agent/.env")
sys.path.append("/wyw/meeting_agent_workspace")

from my_agent.src import asr_tool


def main():
    parser = argparse.ArgumentParser(description="测试全能 ASR 工具")
    parser.add_argument("-a", "--audio", type=str, required=True, help="待测试的音频文件绝对路径")
    args = parser.parse_args()

    audio_file = args.audio
    if not os.path.exists(audio_file):
        print(f"❌ 错误: 找不到音频文件 -> {audio_file}")
        sys.exit(1)

    print(f"🚀 正在启动合体版 ASR Tool 测试...")
    print(f"📂 目标音频: {os.path.basename(audio_file)}")

    try:
        result = asr_tool.invoke({"audio_path": audio_file})

        print("\n" + "="*55)
        print("🎉 工具执行完毕！以下是该工具将返回给 LLM 的精简内容：")
        print("="*55 + "\n")

        print(result)

    except Exception as e:
        print(f"\n❌ 测试过程中发生错误: {e}")


if __name__ == "__main__":
    main()
