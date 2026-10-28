"""Code-owned source spans; references prove provenance, never entailment."""
import re


def source_spans(text_sources):
    spans = []
    for source, text in text_sources.items():
        if source not in {'request', 'speech'} or not isinstance(text, str):
            raise ValueError('Invalid authoritative text source')
        for match in re.finditer(r'[^。！？!?；;\n]+[。！？!?；;]?', text):
            for start in range(match.start(), match.end(), 180):
                end = min(start + 180, match.end())
                if text[start:end].strip():
                    spans.append({'ref': source + ':s' + str(len(spans) + 1),
                                  'source': source, 'start': start, 'end': end,
                                  'quote': text[start:end]})
    return spans


def validate_text_evidence(text_sources, evidence):
    if not isinstance(text_sources, dict) or not isinstance(evidence, list):
        raise ValueError('Invalid text evidence registry')
    expected = {e['ref']: e for e in source_spans(text_sources)}
    seen = set()
    for record in evidence:
        if not isinstance(record, dict) or record.get('ref') not in expected:
            raise ValueError('Unknown text evidence')
        ref = record['ref']
        if ref in seen or record != expected[ref]:
            raise ValueError('Duplicate or changed code-owned text span')
        seen.add(ref)
    return seen
