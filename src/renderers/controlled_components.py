"""Generate basic interactive prototypes from fresh hierarchy state, never HTML input."""
import html
from src.utils.placement_contract import compile_placement_contract, compile_component_contract


def render_controlled_components(state):
    placement = compile_placement_contract(state)
    specs = {e['id']: e for e in compile_component_contract(state)}
    elements = {e['id']: e for e in state['elements']}
    if 'page-root' in elements:
        raise ValueError('Reserved root identity')
    escape = lambda value: html.escape(str(value), quote=True)
    viewport = placement['viewport']
    for key in ('width', 'height'):
        if not isinstance(viewport[key], int) or isinstance(viewport[key], bool) or viewport[key] <= 0:
            raise ValueError('Invalid controlled viewport')
    parts = []
    for position in placement['placements']:
        eid = position['id']; element = elements[eid]; spec = specs[eid]
        kind = spec['source_type']; tag = spec['tag']
        attrs = (f'id="{escape(eid)}" data-parent-id="{escape(position["semantic_parent"] or "")}" '
                 f'data-source-type="{escape(kind)}" style="{escape(position["style"])}"')
        attrs += f' class="component {"passive-region" if kind in {"card","container","navigation","navigation_bar","nav_bar","toolbar","header","footer","modal","image","avatar"} else "foreground"}"'
        text = escape(element.get('text') or '')
        if tag in {'input', 'textarea'}:
            disabled = ' disabled' if spec['disabled'] else ''
            readonly = ' readonly' if spec['readonly'] else ''
            label = element.get('label') or element.get('text') or spec.get('input_type') or 'input'
            attrs += f' aria-label="{escape(label)}" placeholder="{escape(spec["placeholder"])}"{disabled}{readonly}'
            value = escape(element.get('value') or '')
            if tag == 'input':
                parts.append(f'<input {attrs} type="{escape(spec["input_type"])}" value="{value}">')
            else:
                parts.append(f'<textarea {attrs}>{value}</textarea>')
        elif tag == 'button':
            label = spec['label'] or spec.get('action') or eid
            disabled = ' disabled' if element.get('disabled') is True else ''
            attrs += f' type="button" aria-label="{escape(label)}" data-intent-label="{escape(label)}" data-action="{escape(spec.get("action") or "")}"{disabled}'
            parts.append(f'<button {attrs}>{text or escape(label)}</button>')
        else:
            if kind in {'image', 'avatar'}:
                attrs += f' role="img" aria-label="{escape(element.get("text") or kind)}"'
            parts.append(f'<div {attrs}>{text}</div>')
    locale = str(state['page_meta'].get('locale') or 'zh-CN')
    prefix = '已点击：' if locale.lower().startswith('zh') else 'Clicked: '
    # Static delegated code, not interpolated input JS. The feedback confirms a click,
    # not an invented backend or business operation.
    return (f'<!DOCTYPE html><html lang="{escape(locale)}"><head><meta charset="UTF-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>UI prototype</title><style>'
            'html,body{margin:0;padding:0;background:#fff;font-family:Arial,sans-serif;}'
            '.component{min-width:0;min-height:0;max-width:none;max-height:none;overflow:hidden;font-size:14px;line-height:1.2;}'
            '.passive-region{z-index:0;background:#f2f4f6;border:1px solid #b8c0ca;color:#334155;}'
            '.foreground{z-index:1;}[data-source-type="avatar"]{border-radius:50%;}'
            '[data-source-type="divider"]{background:#cbd5e1;}'
            'button.component{border:1px solid #8298b0;background:#edf4fb;color:#17324d;border-radius:4px;padding:2px;cursor:pointer;white-space:nowrap;}'
            'input.component,textarea.component{border:1px solid #8298b0;border-radius:4px;background:#fff;color:#172b40;padding:4px;}'
            'button.component:hover{background:#dceaf8;}button:focus-visible,input:focus-visible,textarea:focus-visible{outline:2px solid #2563eb;outline-offset:-2px;}'
            'button:disabled{cursor:default;opacity:.5;}'
            '</style></head>'
            f'<body data-click-prefix="{escape(prefix)}"><div id="page-root" style="position:relative;width:{viewport["width"]}px;height:{viewport["height"]}px;overflow:hidden;">'
            + ''.join(parts) + '</div><script>'
            'document.getElementById("page-root").addEventListener("click",function(event){'
            'const button=event.target.closest("button[data-intent-label]");'
            'if(!button||button.disabled)return;'
            'window.alert(document.body.dataset.clickPrefix+button.dataset.intentLabel);'
            '});</script></body></html>')
