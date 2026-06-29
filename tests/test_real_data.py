import os
import sys

# 动态获取当前文件所在的目录 (tests)，并向上一级找到 my_agent 根目录
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.abspath(os.path.join(current_dir, ".."))
sys.path.insert(0, parent_dir) # 把 my_agent 加到搜索路径的最前面

from src.workflow import run_agent_workflow

def main():
    # 1. 动态获取当前目录并拼接真实的转写文件路径
    base_dir = os.path.dirname(os.path.abspath(__file__))
    # 注意这里因为脚本在 tests 下，找 outputs 也要退回上一层
    transcript_path = os.path.join(parent_dir, "outputs", "transcripts", "R8001_M8004_MS801_diarization.txt")
    # 2. 读取文件内容
    try:
        with open(transcript_path, "r", encoding="utf-8") as f:
            real_transcript = f.read()
        print(f"✅ 成功加载真实会议记录: {transcript_path}")
        print(f"📊 文本长度: {len(real_transcript)} 字符")
    except FileNotFoundError:
        print(f"❌ 找不到文件: {transcript_path}")
        print("请确认是在 my_agent 目录下运行该脚本。")
        return

    # 3. 组装终极指令给 Planner
    task_prompt = f"""
    以下是一段真实的会议转写记录：
    {real_transcript}
    
    请帮我完成以下任务：
    1. 提取所有业务流转逻辑和排期任务。
    2. 生成业务流程的 Mermaid 流程图 (graph TD)。
    3. 生成项目排期的 Mermaid 甘特图 (gantt，请用相对时间如 1d, 2d 等，或根据文本推断)。
    4. 最终输出一份完整的中文会议总结，将每个人的专属任务总结以及上述两份图表的 Mermaid 代码整合在一起。
    """

    messages = [{"role": "user", "content": task_prompt}]

    print("🚀 正在启动 Agent 工作流，准备深度分析真实会议...")
    
    # 4. 执行工作流
    result = run_agent_workflow(messages=messages, debug=True)

    # 5. 打印并验证最终结果
    if "messages" in result and result["messages"]:
        final_output = result["messages"][-1].content
        print("\n" + "="*30 + " 🎉 最终报告与图表代码 " + "="*30)
        print(final_output)
        print("="*80 + "\n")
        print("💡 提示：请将上面输出的 http://googleusercontent.com/immersive_entry_chip/0")
    else:
        print("❌ 执行异常，请检查终端日志看是哪个 Agent 节点卡住了。")

if __name__ == "__main__":
    main()