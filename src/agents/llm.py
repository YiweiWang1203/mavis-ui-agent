from langchain_ollama import ChatOllama
from src.config.agents import LLMType

# 既然全本地化了，我们就不需要导入原本的 OpenAI/DeepSeek 模块和环境变量了
# 缓存字典的类型提示也改成了 ChatOllama
_llm_cache: dict[LLMType, ChatOllama] = {}

def get_llm_by_type(llm_type: LLMType) -> ChatOllama:
    """
    根据不同的任务类型，分配不同的本地 Ollama 模型。
    如果已经创建过，就直接从缓存里拿。
    """
    if llm_type in _llm_cache:
        return _llm_cache[llm_type]

    if llm_type == "reasoning":
        # 推理任务：分配给本地的 deepseek-r1 (需要你刚才 ollama pull deepseek-r1:14b 下载好)
        llm = ChatOllama(model="deepseek-r1:14b", temperature=0.2)
        
    elif llm_type == "basic":
        # 基础任务：分配给你本地现有的 qwen2.5
        llm = ChatOllama(model="qwen2.5:14b", temperature=0.0)
        
    elif llm_type == "vision":
        # 视觉任务：分配给本地的 llava (需要你刚才 ollama pull llava 下载好)
        llm = ChatOllama(model="llava", temperature=0.0)
        
    else:
        raise ValueError(f"Unknown LLM type: {llm_type}")

    _llm_cache[llm_type] = llm
    return llm

# 初始化缓存实例
reasoning_llm = get_llm_by_type("reasoning")
basic_llm = get_llm_by_type("basic")
vl_llm = get_llm_by_type("vision")

if __name__ == "__main__":
    # 这里的测试代码会直接调用你本地的 deepseek-r1 来流式输出
    print("🚀 正在测试本地推理模型 (deepseek-r1:14b)...")
    stream = reasoning_llm.stream("what is mcp?")
    full_response = ""
    for chunk in stream:
        full_response += chunk.content
        # 实时打印出来的效果
        print(chunk.content, end="", flush=True)
    print("\n✅ 推理模型测试完成！")

    print("🚀 正在测试本地基础模型 (qwen2.5:14b)...")
    basic_response = basic_llm.invoke("Hello")
    print(f"基础模型回复: {basic_response.content}")

    print("🚀 正在测试本地视觉模型 (llava)...")
    vl_response = vl_llm.invoke("Hello")
    print(f"视觉模型回复: {vl_response.content}")