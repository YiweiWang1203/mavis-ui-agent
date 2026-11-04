"""Derive production layout rules from the authoritative tree."""
import re


def region_styles(tree):
    rules = []

    def visit(node):
        escaped = "".join(f"\\{ord(char):x} " for char in node["id"])
        selector = f'[data-ui-id="{escaped}"]'
        declarations = ["min-width:0", "min-height:0", "box-sizing:border-box"]
        if "children" in node:
            declarations += ["display:flex", "flex-direction:" + node["axis"]]
        if node.get("cross_align"):
            alignment = {"start": "flex-start", "end": "flex-end",
                         "center": "center", "stretch": "stretch"}[node["cross_align"]]
            declarations.append("align-self:" + alignment)
        if node.get("grow"):
            declarations.append("flex:1 1 0%")
        if node.get("slot") == "bottom":
            declarations.append("margin-top:auto")
        if node["id"] == "page":
            declarations += ["width:100%", "min-height:100dvh"]
        rules.append(selector + "{" + ";".join(value + " !important" for value in declarations) + "}")
        for child in node.get("children", []):
            visit(child)

    visit(tree)
    return "\n".join(rules)


def attach_region_styles(html, tree):
    endings = list(re.finditer(r"</head\s*>", html, flags=re.I))
    if len(endings) != 1:
        raise ValueError("REGION_HTML_REQUIRES_ONE_HEAD")
    position = endings[0].start()
    style = '<style data-region-contract="2">\n' + region_styles(tree) + "\n</style>\n"
    return html[:position] + style + html[position:]
