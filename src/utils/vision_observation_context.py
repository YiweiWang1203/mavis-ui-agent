"""Separate photo observation input from requested webpage design input."""


def observation_context(user_context, width, height, mode='legacy'):
    if mode == 'legacy':
        return user_context or '请完整解析这张 UI 草图。'
    if mode != 'photo_observation_v1':
        raise ValueError('Unknown vision context mode')
    if any(isinstance(v, bool) or not isinstance(v, int) or v <= 0 for v in (width, height)):
        raise ValueError('Actual photo dimensions required')
    return (f'Observe the visible UI sketch in this entire photograph ({width} pixels wide, {height} pixels high). '
            'Return VisionLayoutPayload observations. Locate each visible object in the photograph; '
            'bbox coordinates refer to the full photograph. Do not design or render a target webpage.')
