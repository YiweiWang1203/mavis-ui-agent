import os
from langchain_core.tools import tool

@tool
def read_file_tool(file_path: str, max_chars: int = 8000) -> str:
    """读取本地文件的内容。
    参数:
    - file_path: 文件的绝对路径或相对路径。
    - max_chars: 最大读取字符数（默认 8000）。用于防止超大文件撑爆大模型的上下文窗口。
    """
    try:
        # 1. 路径安全校验
        if not os.path.exists(file_path):
            return f"[读取失败: 文件不存在 {file_path}]"
        
        if not os.path.isfile(file_path):
            return f"[读取失败: 路径 {file_path} 不是一个有效的文件，可能是目录]"

        # 2. 读取文件（加入 errors="replace" 防止遇到奇葩编码直接报错）
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            # 故意多读一个字符，用来判断文件是否超长
            content = f.read(max_chars + 1) 
            
        # 3. 防爆截断机制
        if len(content) > max_chars:
            safe_content = content[:max_chars]
            warning = (
                f"\n\n...[⚠️ 系统警告：文件过长，已触发安全截断保护！"
                f"当前仅显示前 {max_chars} 个字符。如果需要后续内容，请使用其他工具处理。]"
            )
            return safe_content + warning
        
        return content

    except Exception as e:
        return f"[读取失败: 内部执行出错 - {str(e)}]"
