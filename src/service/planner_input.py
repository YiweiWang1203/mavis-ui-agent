"""Stable user evidence for planning, independent of node status messages."""
import json


def build_planner_intent(state):
    original = state.get('original_user_request')
    if not isinstance(original, str) or not original.strip():
        original = ''
        for message in state.get('messages', []):
            get = message.get if isinstance(message, dict) else lambda key, default=None: getattr(message, key, default)
            if get('type', get('role', '')) in {'human', 'user'} and not get('name'):
                content = get('content')
                if isinstance(content, str) and content.strip():
                    original = content
                    break
    speech = state.get('asr_transcript')
    if not isinstance(speech, str) or not speech.strip():
        speech = state.get('voice_intent')
    if not isinstance(speech, str):
        speech = ''
    platform = state.get('preprocess_platform_hint')
    platform = platform if isinstance(platform, dict) else {}
    return ('[Original User Request]\n' + original + '\n\n[Fresh ASR Transcript]\n' + speech
            + '\n\n[Preprocess Target Platform]\n' + json.dumps(platform, ensure_ascii=False)
            + '\nThis target hint comes from preprocessing, not from evaluation labels. '
              'Use its target_size as the target viewport when supplied and consistent with the explicit user request. '
              'Image orientation describes the photograph, not the requested device. '
              'If no target is supplied, infer from the user request and vision canvas; do not default every page to mobile.')
