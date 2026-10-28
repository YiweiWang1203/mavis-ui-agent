import copy
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from tests import test_frozen_region_planner as fixtures
from src.agents.frozen_region_planner import frozen_inventory
from src.agents.symbolic_flow_planner import generate_symbolic_flow
from src.utils.symbolic_flow_layout import compile_symbolic_flow


class SymbolicFlowTests(unittest.TestCase):
    def fixture(self):
        _, state, vision, kwargs = fixtures.FrozenRegionTests().fixture()
        for e in state['elements']:
            e['parent_id'] = None
        leaf = lambda eid: dict(kind='entity', entity_id=eid, evidence_refs=['vision:' + eid], reason='Synthetic observed control')
        tree = dict(version='symbolic-flow-v1', root=dict(kind='split', id='root', axis='row', weights=[0, 1], children=[leaf('v1'), leaf('v2')], evidence_refs=['vision:v1'], reason='Synthetic ordering'))
        return tree, state, vision, kwargs

    def test_minimum_disjoint_identity_and_inputs(self):
        tree, state, vision, kw = self.fixture()
        before = copy.deepcopy((tree, state, vision))
        result = compile_symbolic_flow(tree, state, vision, **kw)
        self.assertEqual(frozen_inventory(result), frozen_inventory(state))
        a, b = [e['spatial_info']['bbox'] for e in result['elements']]
        self.assertEqual(a, [0, 0, 24, 800])
        self.assertEqual(b, [32, 0, 1000, 800])
        self.assertEqual((tree, state, vision), before)
        self.assertFalse(result['page_meta']['symbolic_flow']['proportions_calibrated'])

    def test_nested_and_photo_geometry_independent(self):
        tree, state, vision, kw = self.fixture()
        child = tree['root']['children'][1]
        tree['root']['children'][1] = dict(kind='split', id='nested', axis='column', weights=[1], children=[child], evidence_refs=['vision:v2'], reason='Nested group')
        first = compile_symbolic_flow(tree, state, vision, **kw)
        kw['frame'] = dict(kw['frame'], width=2400, height=1600, sha256='b' * 64)
        second = compile_symbolic_flow(tree, state, vision, **kw)
        self.assertEqual([e['spatial_info']['bbox'] for e in first['elements']], [e['spatial_info']['bbox'] for e in second['elements']])

    def test_invalid_contracts_and_insufficient_space_fail(self):
        tree, state, vision, kw = self.fixture()
        changes = [lambda t: t['root'].update(bbox=[0, 0, 1, 1]),
                   lambda t: t['root'].update(weights=[float('inf'), 1]),
                   lambda t: t['root'].update(weights=[0, 0]),
                   lambda t: t['root']['children'][0].update(entity_id='unknown'),
                   lambda t: t['root']['children'][1].update(entity_id='v1'),
                   lambda t: t['root']['children'][0].update(evidence_refs=['invented']),
                   lambda t: t['root'].update(children=t['root']['children'][:1], weights=[1])]
        for change in changes:
            t = copy.deepcopy(tree); change(t)
            with self.subTest(tree=t), self.assertRaises(ValueError):
                compile_symbolic_flow(t, state, vision, **kw)
        kw['viewport'] = dict(kw['viewport'], width=50)
        with self.assertRaisesRegex(ValueError, 'Insufficient'):
            compile_symbolic_flow(tree, state, vision, **kw)

    def test_one_call_raw_failure_preserved(self):
        tree, state, vision, kw = self.fixture()
        for valid in (True, False):
            calls = []
            raw = json.dumps(tree if valid else {'version': 'wrong'})
            def create(**args):
                calls.append(args)
                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=raw), finish_reason='stop')])
            client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
            with TemporaryDirectory() as folder:
                args = dict(**kw, image_data_url='data:image/jpeg;base64,AA==', client=client, model='test', output=folder)
                if valid:
                    generate_symbolic_flow(state, vision, **args)
                else:
                    with self.assertRaises(ValueError):
                        generate_symbolic_flow(state, vision, **args)
                self.assertEqual((Path(folder) / 'symbolic_flow_raw.txt').read_text(encoding='utf8'), raw)
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0]['max_tokens'], 8192)
                self.assertEqual(calls[0]['timeout'], 600)
