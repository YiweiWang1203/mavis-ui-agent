from __future__ import annotations

import html
import json
from typing import Any


SUPPORTED_PAGE_KINDS = {"mobile_product_detail"}


def supports_deterministic_rendering(ui_state: dict[str, Any]) -> bool:
    return str((ui_state.get("page_meta") or {}).get("page_kind") or "") in SUPPORTED_PAGE_KINDS


def _bbox(element: dict[str, Any]) -> list[int] | None:
    value = (element.get("spatial_info") or {}).get("bbox")
    if not isinstance(value, list) or len(value) != 4:
        return None
    try:
        x1, y1, x2, y2 = [int(round(float(item))) for item in value]
    except (TypeError, ValueError):
        return None
    return [x1, y1, x2, y2] if x1 < x2 and y1 < y2 else None


def _style_for(element: dict[str, Any], bbox: list[int]) -> str:
    x1, y1, x2, y2 = bbox
    section = str((element.get("spatial_info") or {}).get("section") or "")
    element_type = str(element.get("type") or "unknown").lower()
    font_size = int((element.get("typography") or {}).get("font_size_px") or 14)
    wrap = bool((element.get("typography") or {}).get("wrap"))
    declarations = [
        "position:absolute", f"left:{x1}px", f"top:{y1}px",
        f"width:{x2 - x1}px", f"height:{y2 - y1}px", "box-sizing:border-box",
        f"font-size:{font_size}px",
    ]
    if wrap:
        declarations.extend(["white-space:normal", "overflow-wrap:anywhere"])
    else:
        declarations.extend(["white-space:nowrap", "overflow:hidden", "text-overflow:ellipsis"])
    if element_type in {"button", "icon_button"}:
        declarations.extend(["display:flex", "align-items:center", "justify-content:center", "border:0", "cursor:pointer"])
    if element_type == "image":
        declarations.extend(["display:flex", "align-items:center", "justify-content:center", "background:#f4f4f5", "color:#71717a"])
    if section == "title":
        declarations.extend(["font-weight:650", "color:#18181b"])
    elif section == "price":
        declarations.extend(["font-weight:700", "color:#e54818"])
    elif section == "details":
        declarations.extend(["display:flex", "align-items:center", "color:#3f3f46", "border-bottom:1px solid #f1f1f1"])
    elif section == "bottom_action_bar":
        action = str(element.get("rpa_action") or "").lower()
        color = "#f04420" if any(marker in action for marker in ("buy", "order", "purchase")) else "#f59e0b"
        declarations.extend([f"background:{color}", "color:#fff", "font-weight:600", "border-radius:6px"])
    elif section == "navigation":
        declarations.extend(["background:transparent", "color:#18181b", "font-weight:700"])
    return ";".join(declarations)


def _render_element(element: dict[str, Any]) -> str:
    bbox = _bbox(element)
    if bbox is None:
        return ""
    element_id = html.escape(str(element.get("id") or ""), quote=True)
    element_type = str(element.get("type") or "unknown").lower()
    section = str((element.get("spatial_info") or {}).get("section") or "")
    text = str(element.get("text") or "")
    if section == "navigation" and not text:
        text = "&#x2039;"
    else:
        text = html.escape(text)
    style = html.escape(_style_for(element, bbox), quote=True)
    action = str(element.get("rpa_action") or "")
    onclick = f' onclick="handleRPA({html.escape(json.dumps(action), quote=True)})"' if action else ""

    if element_type in {"button", "icon_button"}:
        aria = html.escape(str(element.get("semantic_role") or element.get("text") or "button"), quote=True)
        return f'    <button id="{element_id}" aria-label="{aria}" style="{style}"{onclick}>{text}</button>'
    if element_type == "image":
        label = text or ("商品图片" if section == "hero" else "图片")
        return f'    <div id="{element_id}" role="img" aria-label="{html.escape(label, quote=True)}" style="{style}">{html.escape(label)}</div>'
    return f'    <div id="{element_id}" style="{style}"{onclick}>{text}</div>'


def render_ui_state_html(ui_state: dict[str, Any]) -> str:
    meta = ui_state.get("page_meta") or {}
    viewport = meta.get("viewport") or {"width": 375, "height": 812}
    width = int(viewport.get("width", 375))
    height = int(viewport.get("height", 812))
    locale = html.escape(str(meta.get("locale") or "zh-CN"), quote=True)
    title = "商品详情" if locale.lower().startswith("zh") else "Product details"
    rendered = [
        _render_element(element) for element in ui_state.get("elements", []) if isinstance(element, dict)
    ]
    body = "\n".join(item for item in rendered if item)
    return f'''<!DOCTYPE html>
<html lang="{locale}">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <style>
    * {{ box-sizing: border-box; }}
    html, body {{ margin: 0; min-height: 100%; background: #f4f4f5; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif; }}
    #app {{ position: relative; width: {width}px; height: {height}px; margin: 0 auto; overflow: hidden; background: #fff; color: #18181b; }}
    button {{ font: inherit; }}
  </style>
</head>
<body>
  <main id="app">
{body}
  </main>
  <script>
    function handleRPA(action) {{
      console.log('RPA action triggered:', action);
    }}
  </script>
</body>
</html>'''
