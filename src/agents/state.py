from typing import TypedDict, List, Optional, Annotated
import operator

class GraphState(TypedDict):
    # 用户最原始的输入
    user_input: str
    image_path: Optional[str]
    audio_path: Optional[str]
    
    # 调度中心产物
    plan: Optional[dict]
    
    # 各个专家的中间产物
    voice_intent: Optional[str]        # Meeting Agent 的结果
    vision_elements: Optional[dict]    # Vision Agent 的坐标结果
    ui_state_json: Optional[dict]      # UI Architect 融合后的契约
    
    # 最终代码
    final_code: Optional[str]
    
    # 错误信息记录
    error: Optional[str]