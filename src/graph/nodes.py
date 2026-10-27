import logging
import json
import re
import base64
import os
from copy import deepcopy
from typing import Literal
from PIL import Image
from langchain_core.messages import HumanMessage
from langgraph.types import Command
from langgraph.graph import END

from src.agents import research_agent, coder_agent, browser_agent, meeting_agent, sa2va_agent
from src.agents.llm import get_llm_by_type
from src.config import TEAM_MEMBERS
from src.config.agents import AGENT_LLM_MAP
from src.prompts.template import apply_prompt_template
from src.tools.search import tavily_tool
from .types import State, Router
from src.agents.ui_architect import generate_ui_state
from src.utils.audit_logger import AuditLogger
from src.tools import vision_tool
from src.tools.vision_ontology_adapter import convert_vision_payload_to_ontology
from src.utils.pipeline_trace import traced_stage

logger = logging.getLogger(__name__)

RESPONSE_FORMAT = "Response from {}:\n\n<response>\n{}\n</response>\n\n*Please execute the next step.*"


def _image_size(path: str | None) -> tuple[int, int] | None:
    if not path or not os.path.exists(path):
        return None
    try:
        with Image.open(path) as img:
            return img.size
    except Exception:
        return None


def _remap_vision_layout_to_layout_image(
    vision_payload: dict,
    recognition_image_path: str | None,
    layout_image_path: str | None,
) -> dict:
    """Map bboxes from recognition-image space into normalized layout-image space.

    The normalizer currently letterboxes the orientation-corrected recognition
    image into the target layout canvas. Vision bboxes are normalized against the
    recognition image, so this remaps them through the same scale and offset.
    """
    if not isinstance(vision_payload, dict) or not recognition_image_path or not layout_image_path:
        return vision_payload
    if os.path.abspath(recognition_image_path) == os.path.abspath(layout_image_path):
        return vision_payload

    recognition_size = _image_size(recognition_image_path)
    layout_size = _image_size(layout_image_path)
    if not recognition_size or not layout_size:
        return vision_payload

    rec_w, rec_h = recognition_size
    layout_w, layout_h = layout_size
    if rec_w <= 0 or rec_h <= 0 or layout_w <= 0 or layout_h <= 0:
        return vision_payload

    scale = min(layout_w / rec_w, layout_h / rec_h)
    resized_w = rec_w * scale
    resized_h = rec_h * scale
    offset_x = (layout_w - resized_w) / 2.0
    offset_y = (layout_h - resized_h) / 2.0

    mapped = deepcopy(vision_payload)
    mapped["canvas"] = {
        "width": int(layout_w),
        "height": int(layout_h),
        "orientation": "portrait" if layout_h > layout_w else ("landscape" if layout_w > layout_h else "square"),
    }

    for element in mapped.get("elements", []) or []:
        bbox = element.get("bbox")
        if not isinstance(bbox, dict):
            continue
        try:
            x_min = float(bbox["x_min"]) * rec_w
            y_min = float(bbox["y_min"]) * rec_h
            x_max = float(bbox["x_max"]) * rec_w
            y_max = float(bbox["y_max"]) * rec_h
        except Exception:
            continue

        lx_min = (x_min * scale + offset_x) / layout_w
        ly_min = (y_min * scale + offset_y) / layout_h
        lx_max = (x_max * scale + offset_x) / layout_w
        ly_max = (y_max * scale + offset_y) / layout_h

        element["bbox"] = {
            "x_min": round(max(0.0, min(1.0, lx_min)), 6),
            "y_min": round(max(0.0, min(1.0, ly_min)), 6),
            "x_max": round(max(0.0, min(1.0, lx_max)), 6),
            "y_max": round(max(0.0, min(1.0, ly_max)), 6),
        }
        element["source"] = element.get("source") or "vision"

    mapped["coordinate_mapping"] = {
        "source": "recognition_to_layout_letterbox",
        "recognition_image_path": recognition_image_path,
        "layout_image_path": layout_image_path,
        "recognition_size": [rec_w, rec_h],
        "layout_size": [layout_w, layout_h],
        "scale": scale,
        "offset": [offset_x, offset_y],
    }
    return mapped


def research_node(state: State) -> Command[Literal["supervisor"]]:
    """Node for the researcher agent that performs research tasks."""
    logger.info("Research agent starting task")
    # audit hook
    try:
        al = state.get('_audit_logger_instance')
        if al:
            al.log_node_start('research_node', {'available_keys': list(state.keys())})
    except Exception:
        pass
    result = research_agent.invoke(state)
    logger.info("Research agent completed task")
    try:
        al = state.get('_audit_logger_instance')
        if al:
            al.log_node_end('research_node', {'messages': len(result.get('messages', []))})
    except Exception:
        pass
    logger.debug(f"Research agent response: {result['messages'][-1].content}")
    return Command(
        update={
            "messages": [
                HumanMessage(
                    content=RESPONSE_FORMAT.format(
                        "researcher", result["messages"][-1].content
                    ),
                    name="researcher",
                )
            ]
        },
        goto="supervisor",
    )


def browser_node(state: State) -> Command[Literal["supervisor"]]:
    """Node for the browser agent that performs web browsing tasks."""
    logger.info("Browser agent starting task")
    try:
        al = state.get('_audit_logger_instance')
        if al:
            al.log_node_start('browser_node', {'available_keys': list(state.keys())})
    except Exception:
        pass
    result = browser_agent.invoke(state)
    logger.info("Browser agent completed task")
    try:
        al = state.get('_audit_logger_instance')
        if al:
            al.log_node_end('browser_node', {'messages': len(result.get('messages', []))})
    except Exception:
        pass
    logger.debug(f"Browser agent response: {result['messages'][-1].content}")
    return Command(
        update={
            "messages": [
                HumanMessage(
                    content=RESPONSE_FORMAT.format(
                        "browser", result["messages"][-1].content
                    ),
                    name="browser",
                )
            ]
        },
        goto="supervisor",
    )


def supervisor_node(state: State) -> Command[str]:
    """Supervisor node that decides which agent should act next."""
    logger.info("Supervisor evaluating next action")
    try:
        al = state.get('_audit_logger_instance')
        if al:
            al.log_node_start('supervisor_node', {'available_keys': list(state.keys())})
    except Exception:
        pass
    
    # Check if we have a parsed plan to execute
    if state.get("parsed_plan") and "steps" in state["parsed_plan"]:
        steps = state["parsed_plan"]["steps"]
        current_step = state.get("current_step", 0)
        
        if current_step < len(steps):
            next_step = steps[current_step]
            agent_name = next_step.get("agent_name")
            
            logger.info(f"Executing step {current_step + 1}/{len(steps)}: {next_step.get('title', 'Unknown')}")
            logger.info(f"Delegating to: {agent_name}")
            
            # Update step counter for next iteration
            return Command(
                goto=agent_name, 
                update={
                    "next": agent_name,
                    "current_step": current_step + 1
                }
            )
        else:
            logger.info("All planned steps completed")
            return Command(goto="__end__", update={"next": "FINISH"})
    
    # Fallback to original supervisor logic if no plan exists
    messages = apply_prompt_template("supervisor", state)
    response = (
        get_llm_by_type(AGENT_LLM_MAP["supervisor"])
        .with_structured_output(Router)
        .invoke(messages)
    )
    goto = response["next"]
    logger.debug(f"Current state messages: {state['messages']}")
    logger.debug(f"Supervisor response: {response}")

    if goto == "FINISH":
        goto = "__end__"
        logger.info("Workflow completed")
    else:
        logger.info(f"Supervisor delegating to: {goto}")

    return Command(goto=goto, update={"next": goto})
    try:
        al = state.get('_audit_logger_instance')
        if al:
            al.log_node_end('supervisor_node', {'goto': goto})
    except Exception:
        pass


def planner_node(state: State) -> Command[Literal["supervisor", "__end__"]]:
    """Planner node that generate the full plan."""
    logger.info("Planner generating full plan")
    try:
        al = state.get('_audit_logger_instance')
        if al:
            al.log_node_start('planner_node', {'available_keys': list(state.keys())})
    except Exception:
        pass
    messages = apply_prompt_template("planner", state)
    # whether to enable deep thinking mode
    llm = get_llm_by_type("basic")
    if state.get("deep_thinking_mode"):
        llm = get_llm_by_type("reasoning")
    if state.get("search_before_planning"):
        try:
            searched_content = tavily_tool.invoke({"query": state["messages"][-1].content})
            # Ensure searched_content is a list of dicts with 'title' and 'content'
            if not isinstance(searched_content, list):
                logger.warning(f"Search tool returned non-list: {searched_content}")
                searched_content = []
            else:
                # Filter out any non-dict or missing keys
                filtered = []
                for elem in searched_content:
                    if isinstance(elem, dict) and 'title' in elem and 'content' in elem:
                        filtered.append({'title': elem['title'], 'content': elem['content']})
                searched_content = filtered
        except Exception as e:
            logger.error(f"Search tool invocation failed: {e}")
            searched_content = []
        messages = deepcopy(messages)
        messages[-1].content += f"\n\n# Relative Search Results\n\n{json.dumps(searched_content, ensure_ascii=False)}"
    
    stream = llm.stream(messages)
    full_response = ""
    for chunk in stream:
        full_response += chunk.content
    logger.debug(f"Current state messages: {state['messages']}")
    logger.debug(f"Planner response: {full_response}")
    try:
        al = state.get('_audit_logger_instance')
        if al:
            al.log_llm_call('planner', getattr(llm, 'name', 'planner_llm'), None, None, None, full_response, {'note': 'planner full_response'})
    except Exception:
        pass

    # Clean up the response to extract JSON
    # Remove thinking tags
    if "<think>" in full_response and "</think>" in full_response:
        start_idx = full_response.find("</think>") + len("</think>")
        full_response = full_response[start_idx:].strip()
    
    # Remove code block markers
    if full_response.startswith("```json"):
        full_response = full_response.removeprefix("```json").strip()
    elif full_response.startswith("```"):
        full_response = full_response.removeprefix("```").strip()

    if full_response.endswith("```"):
        full_response = full_response.removesuffix("```").strip()

    goto = "supervisor"
    # Try to parse the JSON, but first clean up common issues
    cleaned_response = full_response

    # Fix common JSON syntax issues
    # 1. Replace Windows paths backslashes
    cleaned_response = cleaned_response.replace("\\", "\\\\")

    # 2. Fix missing quotes in object keys (common LLM error)
    # Find patterns like {"Key Applications of AI in Meetings", and fix them
    cleaned_response = re.sub(r'{\s*"([^"]+)",\s*"', r'{"title": "\1", "', cleaned_response)
    cleaned_response = re.sub(r'{\s*"([^"]+)",\s*([^"}]+)', r'{"title": "\1", "content": \2', cleaned_response)

    # 3. Try to fix other common issues
    cleaned_response = re.sub(r'{\s*([^"{\s]+),\s*"', r'{"title": "\1", "', cleaned_response)

    try:
        parsed_plan = json.loads(cleaned_response)
        logger.info("Successfully parsed plan JSON")

        # 🌟 提取温馨提示 (如果不存或者不是列表，默认给个空列表)
        warnings = parsed_plan.get("warnings", [])
        if not isinstance(warnings, list):
            warnings = []

        # Store the parsed plan for supervisor to use
        return Command(
            update={
                "messages": [HumanMessage(content=full_response, name="planner")],
                "full_plan": full_response,
                "parsed_plan": parsed_plan,
                "current_step": 0,  # Initialize step counter
                "warnings": warnings, # 👈 将温馨提示写入共享 State 档案袋
            },
            goto=goto,
        )
    except json.JSONDecodeError as e:
        logger.error(f"Planner response is not a valid JSON: {e}")
        logger.debug(f"Raw LLM output: {full_response}")
        
        # Try a more aggressive approach - extract steps manually if JSON parsing fails
        try:
            # 🌟 针对 UI 任务的全新硬编码兜底方案 (替换掉了原来的 reporter)
            simple_plan = {
                "thought": "大模型返回的JSON格式严重错误，触发强制兜底 UI 生成流程。",
                "warnings": ["系统在规划任务时遇到了一点格式小故障，我正在使用基础预设方案为您强行生成页面，可能部分细节会丢失，请见谅。"],
                "title": "Fallback UI Generation",
                "steps": [
                    {
                        "agent_name": "vision_agent",
                        "title": "提取视觉坐标",
                        "description": "尽最大努力分析图片提取坐标。",
                    },
                    {
                        "agent_name": "ui_architect",
                        "title": "数据契约融合",
                        "description": "整合现有的需求和视觉数据生成 UI-State JSON。",
                    },
                    {
                        "agent_name": "coder",
                        "title": "前端代码生成",
                        "description": "基于 JSON 编写可运行的 HTML 代码。",
                    }
                ]
            }
            
            logger.warning("JSON parsing failed, using fallback UI plan structure")
            return Command(
                update={
                    "messages": [HumanMessage(content="Using fallback UI plan due to JSON parsing error", name="planner")],
                    "full_plan": json.dumps(simple_plan, ensure_ascii=False),
                    "parsed_plan": simple_plan,
                    "current_step": 0,
                    "warnings": simple_plan["warnings"], # 👈 兜底方案也要写入 warnings
                },
                goto=goto,
            )
        except Exception as fallback_error:
            logger.error(f"Fallback plan creation also failed: {fallback_error}")
            goto = "__end__"
            
            return Command(
                update={
                    "messages": [HumanMessage(content=f"Plan generation failed: Invalid JSON format", name="planner")],
                    "full_plan": None,
                },
                goto=goto,
            )
    finally:
        try:
            al = state.get('_audit_logger_instance')
            if al:
                al.log_node_end('planner_node', {'parsed_plan_exists': 'parsed_plan' in locals()})
        except Exception:
            pass


def coordinator_node(state: State) -> Command[Literal["planner", "__end__"]]:
    """Coordinator node that communicate with customers."""
    logger.info("Coordinator talking.")
    try:
        al = state.get('_audit_logger_instance')
        if al:
            al.log_node_start('coordinator_node', {'available_keys': list(state.keys())})
    except Exception:
        pass
    messages = apply_prompt_template("coordinator", state)
    response = get_llm_by_type(AGENT_LLM_MAP["coordinator"]).invoke(messages)
    logger.debug(f"Current state messages: {state['messages']}")
    logger.debug(f"reporter response: {response}")

    goto = "__end__"
    if "handoff_to_planner" in response.content:
        goto = "planner"

    return Command(
        goto=goto,
    )
    try:
        al = state.get('_audit_logger_instance')
        if al:
            al.log_node_end('coordinator_node', {'goto': goto})
    except Exception:
        pass


def reporter_node(state: State) -> Command[Literal["supervisor"]]:
    """Reporter node that write a final report."""
    logger.info("Reporter write final report")
    messages = apply_prompt_template("reporter", state)
    response = get_llm_by_type(AGENT_LLM_MAP["reporter"]).invoke(messages)
    logger.debug(f"Current state messages: {state['messages']}")
    logger.debug(f"reporter response: {response}")

    return Command(
        update={
            "messages": [
                HumanMessage(
                    content=RESPONSE_FORMAT.format("reporter", response.content),
                    name="reporter",
                )
            ]
        },
        goto="supervisor",
    )


def meeting_node(state: State) -> Command[Literal["supervisor"]]:
    """Node for the meeting agent that handles meeting topics and audio."""
    logger.info("Meeting agent starting task")
    logger.debug(f"Meeting agent input state: {state}")
    
    has_audio = any("[AUDIO FILE]" in str(getattr(msg, "content", "")) for msg in state.get("messages", []))
    logger.info(f"Audio file detected in messages: {has_audio}")
    
    result = meeting_agent.invoke(state)
    logger.info("Meeting agent completed task")
    
    final_content = result['messages'][-1].content
    logger.debug(f"Meeting agent response: {final_content}")
    
    if has_audio and "<ASR>" not in final_content:
        logger.warning("Audio file was present but no ASR output found in meeting_agent response")
    
    return Command(
        update={
            "messages": [
                HumanMessage(
                    content=RESPONSE_FORMAT.format("meeting_agent", final_content),
                    name="meeting_agent",
                )
            ],
            "voice_intent": final_content 
        },
        goto="supervisor",
    )


@traced_stage('graph.ui_architect_node')
def ui_architect_node(state: State) -> Command[Literal["supervisor"]]:
    """Node for the UI Architect: 融合多模态数据，生成标准 JSON 契约"""
    logger.info("UI Architect 正在严谨地融合多模态数据数据...")
    try:
        al = state.get('_audit_logger_instance')
        if al:
            al.log_node_start('ui_architect_node', {'available_keys': list(state.keys())})
    except Exception:
        pass
    
    # === 1. 强制隔离逻辑 ===
    original_prompt = state["messages"][0].content
    intent = state.get("voice_intent", "用户未提供音频需求。")
    vision_elements = state.get("vision_elements")

    # 如果用户提供了图片标记，则必须有有效的视觉输出
    image_present = bool(re.search(r'\[IMAGE\]:\s*([^\s\n]+)', original_prompt))
    if image_present:
        vision_status = state.get('vision_status')
        if not vision_elements or not vision_status or not vision_status.get('valid'):
            logger.error('🛑 UI Architect: required vision data missing or invalid for image-based task')
            fail_json = {"error": "视觉分析数据缺失或无效，无法生成 UI-State JSON"}
            return Command(
                update={
                    "ui_state_json": fail_json,
                    "messages": [HumanMessage(content="Response from ui_architect:\n\n<response>\n🛑 视觉数据缺失或无效，数据契约构建停止。\n</response>", name="ui_architect")],
                    "warnings": state.get("warnings", []) + ["必须提供有效的视觉坐标才能生成 UI-State JSON。"]
                },
                goto="supervisor"
            )

    # 正常的数据合成业务逻辑
    combined_intent = f"【总体审美要求】\n{original_prompt}\n\n【语音/文本细节需求】\n{intent}"
    result_json = generate_ui_state(combined_intent, vision_elements, preferred_locale=state.get("preferred_locale"))

    try:
        al = state.get('_audit_logger_instance')
        if al:
            al.save_prompt_snapshot('ui_architect_intent', combined_intent)
            al.save_state_snapshot('ui_architect_input', {'vision_elements_present': bool(vision_elements)})
            al.log_llm_call('ui_architect', 'ui_architect_model', combined_intent, None, None, json.dumps(result_json, ensure_ascii=False) if result_json else None)
    except Exception:
        pass
    
    # 做法：假设 generate_ui_state 内部已经确保了元素的坐标是匹配标准 375x812 的

    return Command(
        update={
            "ui_state_json": result_json,
            "messages": [
                HumanMessage(content=RESPONSE_FORMAT.format("ui_architect", json.dumps(result_json, ensure_ascii=False, indent=2)), name="ui_architect")
            ]
        },
        goto="supervisor",
    )
    try:
        al = state.get('_audit_logger_instance')
        if al:
            al.log_node_end('ui_architect_node', {'ui_state_keys': list(result_json.keys()) if isinstance(result_json, dict) else {}})
    except Exception:
        pass


def sa2va_node(state: State) -> Command[Literal["supervisor"]]:
    """Node for the sa2va agent that handles video/image content Q&A."""
    logger.info("Sa2VA agent starting task")
    try:
        al = state.get('_audit_logger_instance')
        if al:
            al.log_node_start('sa2va_node', {'available_keys': list(state.keys())})
    except Exception:
        pass
    
    # 🌟 核心隔离逻辑：只取第一条消息（最纯净的用户原始输入，包含 [IMAGE] 路径）
    original_user_msg = state["messages"][0]
    clean_state = deepcopy(state)
    
    user_content = original_user_msg.content
    
    # 🔍 核心修复：用正则提取指令中的本地图片路径
    # 匹配 [IMAGE]: /path/to/file.png 格式
    image_match = re.search(r'\[IMAGE\]:\s*([^\s\n]+)', user_content)
    
    if image_match:
        image_path = image_match.group(1)
        if os.path.exists(image_path):
            try:
                # 1. 读取本地图片并进行 Base64 编码
                with open(image_path, "rb") as image_file:
                    base64_image = base64.b64encode(image_file.read()).decode("utf-8")
                
                # 2. 组装符合 LangChain 规范的多模态消息体
                multimodal_content = [
                    {"type": "text", "text": user_content},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{base64_image}"}
                    }
                ]
                # 3. 用多模态消息覆盖纯文本消息
                clean_state["messages"] = [HumanMessage(content=multimodal_content)]
                logger.info(f"✅ 成功将本地图片转化为 Base64 并注入多模态状态: {image_path}")
            except Exception as e:
                logger.error(f"❌ 读取图片或转换 Base64 失败: {str(e)}")
                clean_state["messages"] = [original_user_msg]
        else:
            logger.warning(f"⚠️ 检测到图片标记，但本地路径不存在: {image_path}")
            clean_state["messages"] = [original_user_msg]
    else:
        # 如果确实没有图片标记，保持原样（纯文本降级处理）
        clean_state["messages"] = [original_user_msg]
    
    # 拿着已经注入了真实图片数据的状态去跑底层视觉大模型
    result = sa2va_agent.invoke(clean_state)
    logger.info("Sa2VA agent completed task")
    
    content = result["messages"][-1].content
    
    # 尝试提取视觉模型的 JSON 输出
    try:
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        elements = json.loads(json_match.group()) if json_match else {"raw_info": content}
    except:
        elements = {"error": "解析坐标失败", "raw": content}

    try:
        al = state.get('_audit_logger_instance')
        if al:
            # image_path extracted earlier when preparing multimodal
            image_match = re.search(r'\[IMAGE\]:\s*([^\s\n]+)', state['messages'][0].content)
            image_path = image_match.group(1) if image_match else None
            al.log_vision_call('sa2va', image_path or '', None, content, {'parsed_elements_summary': list(elements.keys()) if isinstance(elements, dict) else None})
            al.save_state_snapshot('sa2va_output', elements)
    except Exception:
        pass

    return Command(
        update={
            "messages": [
                HumanMessage(
                    content=RESPONSE_FORMAT.format("sa2va_agent", content),
                    name="sa2va_agent",
                )
            ],
            "vision_elements": elements # 🌟 将真实的视觉结果存入状态
        },
        goto="supervisor",
    )


@traced_stage('graph.vision_node')
def vision_node(state: State) -> Command[Literal["supervisor"]]:
    """Deterministic vision node: always call extract_ui_layout directly and validate."""
    logger.info("Vision node starting deterministic UI extraction")
    al = state.get('_audit_logger_instance')

    # Extract image path from the very first (pure) user message
    original_user_msg = state['messages'][0]
    user_content = getattr(original_user_msg, 'content', '')
    image_match = re.search(r'\[IMAGE\]:\s*([^\s\n]+)', user_content)
    image_path = image_match.group(1) if image_match else None

    if not image_path:
        msg = "No image path provided in the first message. Vision node aborting."
        logger.error(msg)
        return Command(update={
            "vision_elements": None,
            "vision_status": {"valid": False, "errors": ["no_image_path"]},
            "vision_raw_output": None,
            "vision_retry_count": 0,
            "messages": [HumanMessage(content=msg, name="vision")]
        }, goto="supervisor")

    # Do not mutate state in place; prepare updates via Command
    max_retries = 1
    retry_count = 0
    audit = al

    # First extraction
    # compute image complexity metrics
    complexity = vision_tool.analyze_image_complexity(image_path)

    try:
        raw_out = vision_tool.extract_ui_layout(
            image_path=image_path,
            user_context=state.get('voice_intent') or user_content,
            previous_layout=None,
            repair_feedback=None,
            audit_logger=audit
        )
    except TypeError:
        # backward-compatible call for tests or older stubs
        raw_out = vision_tool.extract_ui_layout(image_path, state.get('voice_intent') or user_content, audit)
    # validate
    validated, validation = vision_tool.validate_vision_layout(raw_out, image_path=image_path)

    # If invalid or low completeness, attempt one repair/retry
    if (not validation.valid or validation.completeness_score < float(os.getenv('VISION_COMPLETENESS_THRESHOLD', '0.5'))) and retry_count < max_retries:
        retry_count += 1
        # prepare repair feedback object
        repair_feedback = {
            'previous_validation': validation.model_dump() if hasattr(validation, 'model_dump') else getattr(validation, '__dict__', None),
            'previous_diagnostics': raw_out.get('diagnostics') if isinstance(raw_out, dict) else None,
            'complexity': complexity,
        }
        try:
            raw_out2 = vision_tool.extract_ui_layout(
                image_path=image_path,
                user_context=state.get('voice_intent') or user_content,
                previous_layout=raw_out.get('payload') if isinstance(raw_out, dict) else None,
                repair_feedback=repair_feedback,
                audit_logger=audit
            )
        except TypeError:
            # fallback for tests/mocks
            raw_out2 = vision_tool.extract_ui_layout(image_path, state.get('voice_intent') or user_content, audit)
        validated2, validation2 = vision_tool.validate_vision_layout(raw_out2, image_path=image_path)
        # choose better result using deterministic comparator
        try:
            choose_second = vision_tool.select_better_vision_result(validated, validation, validated2, validation2, complexity=complexity)
        except Exception:
            choose_second = False

        if choose_second:
            validated, validation = validated2, validation2
            raw_out = raw_out2

    layout_image_path = state.get("layout_image_path")
    recognition_image_path = state.get("recognition_image_path") or image_path
    if validation.valid and layout_image_path and recognition_image_path:
        validated = _remap_vision_layout_to_layout_image(
            validated,
            recognition_image_path=recognition_image_path,
            layout_image_path=layout_image_path,
        )

    # Log and save snapshot
    try:
        if audit:
            audit.log_vision_call('vision_node', image_path or '', None, None, {
                'model': os.getenv('VISION_MODEL'),
                'raw_element_count': len(validated.get('elements', [])) if isinstance(validated, dict) else None,
                'validated_element_count': validation.element_count,
                'completeness_score': validation.completeness_score,
                'validation_errors': validation.errors,
                'validation_warnings': validation.warnings,
                'retry_count': retry_count,
            })
            audit.save_state_snapshot('vision_elements_saved', validated)
    except Exception:
        pass

    if not validation.valid:
        return Command(update={
            'image_path': image_path,
            'vision_elements': None,
            'vision_elements_v0_1': None,
            'vision_status': validation.model_dump() if hasattr(validation, 'model_dump') else validation.__dict__,
            'vision_raw_output': str(raw_out),
            'vision_retry_count': retry_count,
            'messages': [HumanMessage(content='Vision extraction failed validation and aborted.', name='vision')]
        }, goto='supervisor')

    vision_elements_v0_1 = convert_vision_payload_to_ontology(validated)

    return Command(update={
        'image_path': image_path,
        'vision_elements': validated,
        'vision_elements_v0_1': vision_elements_v0_1,
        'vision_status': validation.model_dump() if hasattr(validation, 'model_dump') else validation.__dict__,
        'vision_raw_output': str(raw_out),
        'vision_retry_count': retry_count,
        'messages': [HumanMessage(content=RESPONSE_FORMAT.format('vision_agent', 'Vision extraction successful'), name='vision')]
    }, goto='supervisor')

@traced_stage('graph.code_node')
def code_node(state: State) -> Command[Literal["supervisor"]]:
    """Node for the coder agent that executes Python code and saves HTML."""
    logger.info("Code agent starting task")
    
    # === 1. 检查必要的前置数据 (数据契约) ===
    ui_json = state.get("ui_state_json")
    if not ui_json or ui_json.get("error"):
        logger.error("Coder can't proceed without a valid UI-State JSON contract.")
        return Command(
            update={
                "messages": [HumanMessage(content="Coder 停止：缺少有效的 UI-State JSON 数据契约，无法生成代码。", name="coder")],
                "final_code": None
            },
            goto="supervisor"
        )

    # === 2. 🌟 核心隔离逻辑：直接调用代码生成函数，跳过 ReAct agent ===
    # 问题：原来的 coder_agent 会被用户原始需求中的图片路径干扰
    # 解决方案：直接调用 generate_frontend_code 函数，只传递 UI-State JSON
    from src.agents.coder import generate_frontend_code
    al = state.get('_audit_logger_instance')
    result = generate_frontend_code(ui_json, audit_logger=al)
    
    # 处理返回结果
    if isinstance(result, dict):
        code_str = result.get("code", "")
        renderer = result.get("renderer", "llm")
        file_path = result.get("file_path", "未找到路径 (可能已保存在默认目录)")
        final_code = code_str
        content = f"已根据 UI-State JSON 生成前端代码。"
    else:
        code_str = str(result)
        renderer = "llm"
        file_path = "未找到路径"
        final_code = code_str
        content = code_str

    return Command(
        update={
            "messages": [
                HumanMessage(
                    content=RESPONSE_FORMAT.format(
                        "coder", f"{content}\n\n✅ 文件已保存至: {file_path}"
                    ),
                    name="coder",
                )
            ],
            "final_code": final_code, # 🌟 把核心资产装入主状态
            "final_code_path": file_path,
            "final_renderer": renderer,
        },
        goto="supervisor",
    )
