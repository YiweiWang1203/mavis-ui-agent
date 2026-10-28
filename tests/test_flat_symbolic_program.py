import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from tests import test_symbolic_flow_layout as fixtures
from src.utils.symbolic_flow_layout import expand_flat_program, compile_symbolic_flow
from src.agents.symbolic_flow_planner import generate_symbolic_flow


def flatten(tree):
    rows = []
    def visit(n, parent=None, weight=1):
        rid = n.get('id', 'node_' + n.get('entity_id', ''))
        r = {k:copy.deepcopy(n[k]) for k in ['kind','evidence_refs','reason']}
        r.update(id=rid,parent_id=parent,weight=weight)
        if n['kind']=='split':
            r['axis']=n['axis']
        else:
            r['entity_id']=n['entity_id']
        rows.append(r)
        if n['kind']=='split':
            for child,w in zip(n['children'],n['weights']):visit(child,rid,w)
    visit(tree['root'])
    return dict(version='symbolic-flat-v1',nodes=rows)


class FlatProgramTests(unittest.TestCase):
    def test_same_layout_and_identity_as_original_tree(self):
        tree,state,vision,kw=fixtures.SymbolicFlowTests().fixture()
        program=flatten(tree); original=copy.deepcopy(program)
        a=compile_symbolic_flow(tree,state,vision,**kw)
        b=compile_symbolic_flow(expand_flat_program(program),state,vision,**kw)
        self.assertEqual(a,b)
        self.assertEqual(program,original)
        # Parent ordering irrelevant, sibling order remains meaningful.
        program['nodes']=program['nodes'][1:]+program['nodes'][:1]
        self.assertEqual(expand_flat_program(program),tree)

    def test_bad_graphs_and_coordinate_injection_rejected(self):
        tree,_,_,_=fixtures.SymbolicFlowTests().fixture();p=flatten(tree)
        changes=[lambda x:x['nodes'].append(copy.deepcopy(x['nodes'][0])),
                 lambda x:x['nodes'][1].update(parent_id='unknown'),
                 lambda x:x['nodes'][1].update(parent_id=None),
                 lambda x:x['nodes'][2].update(parent_id=x['nodes'][1]['id']),
                 lambda x:x['nodes'][0].update(parent_id=x['nodes'][0]['id']),
                 lambda x:x['nodes'][1].update(weight=float('nan')),
                 lambda x:x['nodes'][1].update(bbox=[0,0,1,1])]
        for change in changes:
            q=copy.deepcopy(p);change(q)
            with self.subTest(q=q),self.assertRaises(ValueError):expand_flat_program(q)

    def test_missing_entity_never_filled(self):
        tree,state,vision,kw=fixtures.SymbolicFlowTests().fixture();p=flatten(tree);p['nodes'].pop();p['nodes'][1]['weight']=1
        with self.assertRaisesRegex(ValueError,'inventory incomplete'):
            compile_symbolic_flow(expand_flat_program(p),state,vision,**kw)

    def test_provider_one_call_and_both_program_and_tree_preserved(self):
        tree,state,vision,kw=fixtures.SymbolicFlowTests().fixture();program=flatten(tree);calls=[]
        def create(**args):
            calls.append(args)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(program)),finish_reason='stop')])
        client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        with TemporaryDirectory() as folder:
            generate_symbolic_flow(state,vision,**kw,image_data_url='data:image/jpeg;base64,AA==',client=client,model='test',output=folder,flat_program=True)
            self.assertEqual(json.loads((Path(folder)/'symbolic_flow_parsed.json').read_text(encoding='utf8')),program)
            self.assertEqual(json.loads((Path(folder)/'symbolic_flow_expanded.json').read_text(encoding='utf8')),tree)
        self.assertEqual(len(calls),1)
        self.assertEqual(calls[0]['timeout'],600)
