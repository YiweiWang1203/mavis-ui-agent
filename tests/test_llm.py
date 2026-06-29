from langchain_community.chat_models import ChatOllama
from langchain_core.messages import HumanMessage

print("正在尝试连接本地 Ollama 引擎...")

# 初始化本地大模型
llm = ChatOllama(
    model="qwen2.5:14b", 
    base_url="http://localhost:11434",
    temperature=0.7
)

# 构建测试问题
messages = [
    HumanMessage(content="你好！请扮演一名会议助理，用一句话告诉我你现在运行在什么硬件上？")
]

# 发送请求并获取回答
print("正在调用 Qwen2.5，如果卡住了说明在加载模型进显存...")
response = llm.invoke(messages)

print("\n模型回答：")
print("-" * 40)
print(response.content)
print("-" * 40)
