"""Apply explicit localized browser feedback to a complete native page."""
import json

from src.service.direct_multimodal_baseline import submit_direct_html


NATIVE_HTML_REPAIR = "native_html_localized_repair_v1"
REPAIR_INSTRUCTION = (
    "This is a localized repair of the supplied initial HTML. Use the human browser feedback to fix only the "
    "stated target. Preserve the page's unrelated content, structure, appearance and existing behaviors. "
    "Return the entire repaired HTML document, not a diff or explanation. The original icon references and "
    "accepted bounded static CSS SVG remain available; do not introduce new external or encoded assets."
)


def run_native_html_localized_repair(frozen_request, initial_html, feedback, output):
    system, user = frozen_request["messages"]
    text, image = user["content"]
    if (system["role"], user["role"], text["type"], image["type"]) != ("system", "user", "text", "image_url"):
        raise ValueError("NATIVE_REPAIR_REQUIRES_FROZEN_MULTIMODAL_REQUEST")
    payload = json.loads(text["text"])
    request = {
        **frozen_request,
        "messages": [
            {**system, "content": system["content"] + "\n\n" + REPAIR_INSTRUCTION},
            {**user, "content": [
                {**text, "text": json.dumps({**payload, "initial_html": initial_html,
                                            "human_browser_feedback": feedback}, ensure_ascii=False)},
                image,
            ]},
        ],
    }
    return submit_direct_html(request, output, allow_bounded_css_svg=True)
