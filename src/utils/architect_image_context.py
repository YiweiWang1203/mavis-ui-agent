"""Explicit observation-image transport, independent of prompt and geometry policy."""


def architect_request_content(text, structure_mode, image_data_url=None, *, attach_observation_image=False):
    if not isinstance(attach_observation_image, bool):
        raise ValueError('Observation image switch must be boolean')
    legacy_image = structure_mode in {'hierarchy_registry_image_v1', 'hierarchy_node_evidence_v1'}
    if not legacy_image and not attach_observation_image:
        return text
    if attach_observation_image and structure_mode != 'hierarchy_v1':
        raise ValueError('Isolated observation image requires hierarchy_v1')
    if not isinstance(image_data_url, str) or not image_data_url.startswith('data:image/') or ';base64,' not in image_data_url:
        raise ValueError('Image-grounded architect requires the existing image data URL')
    return [{'type': 'text', 'text': text},
            {'type': 'image_url', 'image_url': {'url': image_data_url}}]
