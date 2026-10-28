import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from src.utils.semantic_page_plan import compile_semantic_plan, parse_semantic_json
from src.utils.text_evidence_contract import source_spans, validate_text_evidence


def fixture():
    from tests.test_region_layout_contract import fixture as regions
    state, vision, frame, viewport, region_plan = regions()
    request, speech = 'Build a desktop page.', 'Put the editor under the content.'
    spans = source_spans({'request': request, 'speech': speech})
    speech_id = spans[-1]['ref']
    region_plan['regions'][2]['evidence_refs'] = [speech_id]
    plan = {'version': 'semantic-page-v1', 'region_plan': region_plan,
        'entities': [{'id': v['id'], 'type': v['type'], 'text': v.get('text') or '',
          'parent_id': 'v1' if v['id'] == 'v2' else None, 'rpa_action': '',
          'evidence_refs': ['vision:' + v['id']]} for v in vision['elements']],
        'requirements': [{'id': 'req_a', 'source_id': speech_id, 'intent': 'Editor below content',
           'entity_ids': ['v2'], 'status': 'accepted', 'reason': 'Synthetic declaration, semantics not proven'}],
        'source_dispositions': [{'source_id': s['ref'], 'status': 'used' if s['ref'] == speech_id else 'context',
            'reason': 'Synthetic source disposition'} for s in spans],
        'observation_dispositions': [{'vision_id': v['id'], 'status': 'accepted', 'reason': 'Observed object retained'}
            for v in vision['elements']]}
    kwargs = dict(request=request, speech=speech, frame=frame, viewport=viewport)
    return plan, vision, kwargs


class SemanticPagePlanTests(unittest.TestCase):
    def test_source_quotes_come_from_code_and_flow_through_region_compiler(self):
        plan, vision, kwargs = fixture()
        original = copy.deepcopy((plan, vision, kwargs))
        state = compile_semantic_plan(plan, vision, **kwargs)
        meta = state['page_meta']['semantic_plan']
        self.assertEqual(meta['requirements'][0]['source']['quote'], kwargs['speech'])
        self.assertEqual(state['elements'][1]['spatial_info']['bbox'], [325, 656, 925, 752])
        self.assertIsNone(meta['all_user_intent_covered'])
        self.assertEqual((plan, vision, kwargs), original)

    def test_spans_preserve_unicode_offsets_and_cannot_be_rewritten(self):
        sources = {'speech': '说话。下一句\n' + '甲' * 200}
        spans = source_spans(sources)
        for span in spans:
            self.assertEqual(span['quote'], sources[span['source']][span['start']:span['end']])
        spans[0]['quote'] = 'invented'
        with self.assertRaises(ValueError):
            validate_text_evidence(sources, spans)

    def test_missing_unknown_duplicate_or_retyped_data_is_not_repaired(self):
        changes = [lambda p: p.pop('requirements'),
            lambda p: p['source_dispositions'].pop(),
            lambda p: p['observation_dispositions'].pop(),
            lambda p: p['entities'].pop(),
            lambda p: p['entities'][1].update(type='button'),
            lambda p: p['entities'][1].update(text='invented'),
            lambda p: p['requirements'][0].update(source_id='speech:unknown'),
            lambda p: p['requirements'][0].update(entity_ids=['unknown']),
            lambda p: p['requirements'][0].update(entity_ids=[]),
            lambda p: p['region_plan']['regions'][0].update(evidence_refs=['speech:unknown']),
            lambda p: p.update(text_sources={'speech': 'fabricated'}),
            lambda p: p['source_dispositions'][1].update(status='context')]
        for index, change in enumerate(changes):
            with self.subTest(index=index):
                plan, vision, kwargs = fixture()
                change(plan)
                with self.assertRaises(ValueError):
                    compile_semantic_plan(plan, vision, **kwargs)

    def test_empty_or_unresolved_requirements_are_not_coverage_success(self):
        plan, vision, kwargs = fixture()
        plan['requirements'] = []
        meta = compile_semantic_plan(plan, vision, **kwargs)['page_meta']['semantic_plan']
        self.assertEqual((meta['requirement_accepted'], meta['requirement_proposed']), (0, 0))
        self.assertEqual(meta['status'], 'page_plan_incomplete')
        plan, vision, kwargs = fixture()
        plan['requirements'][0].update(status='unresolved', entity_ids=[])
        self.assertEqual(compile_semantic_plan(plan, vision, **kwargs)['page_meta']['semantic_plan']['status'], 'page_plan_incomplete')

    def test_duplicate_json_and_nonfinite_values_are_rejected(self):
        for raw in ['{"a":1,"a":2}', '{"bbox":[NaN,1,2,3]}']:
            with self.assertRaises(ValueError):
                parse_semantic_json(raw)

    def test_single_call_agent_saves_raw_and_never_retries_validation_failure(self):
        from src.agents.semantic_page_planner import generate_semantic_page_plan
        plan, vision, kwargs = fixture()
        requests = []
        def create(**request):
            requests.append(request)
            return SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop',
                message=SimpleNamespace(content=json.dumps(plan)))])
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        root = Path(__file__).resolve().parents[1] / 'outputs/contract_test_tmp'
        root.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=root) as folder:
            generate_semantic_page_plan(vision, **kwargs, image_data_url='data:image/jpeg;base64,AA==',
                client=client, model='fixed-test-model', output=folder)
            self.assertTrue((Path(folder) / 'semantic_plan_raw.txt').is_file())
            self.assertEqual(requests[0]['max_tokens'], 8192)
        self.assertEqual(len(requests), 1)
        plan.pop('requirements')
        with TemporaryDirectory(dir=root) as folder:
            with self.assertRaises(ValueError):
                generate_semantic_page_plan(vision, **kwargs, image_data_url='data:image/jpeg;base64,AA==',
                    client=client, model='fixed-test-model', output=folder)
        self.assertEqual(len(requests), 2)


if __name__ == '__main__':
    unittest.main()
