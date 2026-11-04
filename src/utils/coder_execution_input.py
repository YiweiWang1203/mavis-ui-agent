"""Project the authoritative execution contract without diagnostic review text."""
from copy import deepcopy
import json


def coder_execution_state(state):
    result = {key: deepcopy(state[key]) for key in
              ("region_tree", "elements", "requirements", "actions") if key in state}
    metadata = state.get("page_meta", {})
    result["page_meta"] = {key: deepcopy(metadata[key]) for key in
                           ("viewport", "structure_mode", "contract_version", "locale")
                           if key in metadata}
    return result


def coder_user_content(state, original_request, transcript):
    return ("Generate runnable frontend code from the following UI-State JSON.\n\n"
            + json.dumps(state, ensure_ascii=False, indent=2)
            + "\n\n[Original User Request]\n" + original_request
            + "\n\n[Fresh ASR Transcript]\n" + transcript)
