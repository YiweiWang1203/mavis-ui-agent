import logging
import os
import sys
from dotenv import load_dotenv

current_dir = os.path.dirname(os.path.abspath(__file__)) # 这是 src 目录
# 1. 拿到 my_agent 目录 (src 的上一层)
my_agent_dir = os.path.abspath(os.path.join(current_dir, "../"))
# 2. 拿到 workspace 根目录
project_root = os.path.abspath(os.path.join(my_agent_dir, "../"))

# 将这两个路径都塞进 Python 的搜索口袋
if my_agent_dir not in sys.path:
    sys.path.insert(0, my_agent_dir) # 优先级最高，让内部文件能找到 from src...
if project_root not in sys.path:
    sys.path.append(project_root)    # 保证外部调用 my_agent.src 也能通
# ---------------------

# 2. 注入环境变量 (工业级标配)
# 寻找 .env 文件：它应该在 my_agent 目录下
dotenv_path = os.path.join(my_agent_dir, ".env")
load_dotenv(dotenv_path)

# 此时这行代码和子文件里的 from src... 都能完美运行了
from src.config import TEAM_MEMBERS
from src.graph import build_graph

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

def enable_debug_logging():
    logging.getLogger("my_agent.src").setLevel(logging.DEBUG)

logger = logging.getLogger(__name__)

# 创建图 (大脑连接完成)
try:
    graph = build_graph()
except Exception as e:
    logger.error(f"❌ 构筑 Agent 大脑失败，请检查工具链初始化: {e}")
    raise

def run_agent_workflow(messages: list[dict], debug: bool = False):
    if not messages or not any(m.get("content") for m in messages):
        raise ValueError("Input messages could not be empty")

    if debug:
        enable_debug_logging()

    logger.info(f"🚀 启动 Agent 工作流...")
    
    # 这里的 invoke 会真正进入 LangGraph 的循环
    result = graph.invoke(
        {
            "TEAM_MEMBERS": TEAM_MEMBERS,
            "messages": messages,
            "deep_thinking_mode": True,
            "search_before_planning": True,
        }
    )
    logger.info("✅ 工作流执行成功")
    return result

if __name__ == "__main__":
    # 尝试打印流程图代码 (Mermaid 格式)
    print("\n" + "="*20 + " AGENT 逻辑流程图 (Mermaid) " + "="*20)
    try:
        print(graph.get_graph().draw_mermaid())
    except:
        print("提示: 环境暂不支持绘图，但逻辑已就绪。")
    print("="*60 + "\n")