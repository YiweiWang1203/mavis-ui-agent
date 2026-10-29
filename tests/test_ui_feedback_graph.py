import copy
import unittest

try:
    from src.graph.ui_feedback_graph import build_ui_feedback_graph
    LANGGRAPH_AVAILABLE = True
except ModuleNotFoundError as exc:
    if exc.name != 'langgraph':
        raise
    build_ui_feedback_graph = None
    LANGGRAPH_AVAILABLE = False


def fixture():
    vision = {'canvas': {'width': 406, 'height': 720}, 'elements': [
        {'id': 'e1', 'type': 'button', 'text': 'Send',
         'bbox': {'x_min': .1, 'y_min': .1, 'x_max': .2, 'y_max': .2}},
    ]}
    provenance = {
        'observation_frame': {'id': 'frame', 'width': 406, 'height': 720, 'sha256': 'a' * 64},
        'target_viewport': {'id': 'pc', 'width': 1440, 'height': 900},
    }
    element = {'id': 'e1', 'vision_id': 'e1', 'origin': 'vision', 'type': 'button',
               'text': 'Send', 'parent_id': None, 'rpa_action': 'click',
               'spatial_info': {'bbox': [1440, 900, 1440, 900],
                   'coordinate_space': 'viewport_px', 'viewport_id': 'pc',
                   'derivation': {'kind': 'semantic_layout', 'evidence_refs': ['vision:e1'],
                                  'reason': 'target decision'}}}
    invalid = {'page_meta': {'viewport': {'width': 1440, 'height': 900}, 'locale': 'en'},
               'elements': [element]}
    valid = copy.deepcopy(invalid)
    valid['elements'][0]['spatial_info']['bbox'] = [100, 100, 300, 180]
    first = {'attempt_id': 'architect-0', 'status': 'parsed', 'parsed': invalid,
             'raw_response': 'first-raw', 'finish_reason': 'stop'}
    repair = {'attempt_id': 'architect-1', 'status': 'parsed', 'parsed': valid,
              'raw_response': 'repair-raw', 'finish_reason': 'stop'}
    state = {'user_intent': 'send button', 'vision_elements': vision,
             'trusted_coordinate_context': provenance, 'attempts': [first],
             'feedback_history': [], 'quality_history': [], 'route_history': [],
             'downstream_history': [], 'pending_feedback': None,
             'ui_state_json': {'old': True}, 'final_code': '<html>old</html>',
             'browser_audit': {'old': True}, 'model_call_count': 0, 'model_call_limit': 1}
    return state, repair


@unittest.skipUnless(LANGGRAPH_AVAILABLE, 'LangGraph is verified in the project Ubuntu UV, not installed in local system Python')
class UIFeedbackGraphTests(unittest.TestCase):
    def test_candidate_returns_once_repairs_revalidates_and_invalidates_old_downstream(self):
        state, repair = fixture(); calls = []
        def architect_call(**kwargs):
            calls.append(copy.deepcopy(kwargs)); return copy.deepcopy(repair)
        graph = build_ui_feedback_graph(architect_call, lambda value: '<html>new</html>', allow_repair=True)
        result = graph.invoke(state)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]['correction_feedback']['source_attempt_id'], 'architect-0')
        self.assertEqual(calls[0]['correction_feedback']['original_raw_response'], 'first-raw')
        self.assertEqual(calls[0]['correction_feedback']['original_state'], state['attempts'][0]['parsed'])
        self.assertEqual(calls[0]['correction_feedback']['allowed_changes'], [
            {'object_id':'e1','field':'spatial_info.bbox'}])
        self.assertNotIn('allowed_fields', calls[0]['correction_feedback'])
        self.assertEqual([item['action'] for item in result['route_history']], [
            'reuse_shared_first_attempt', 'rejected', 'return_to_ui_architect_once',
            'repair', 'valid', 'release_to_render', 'render_validated_state'])
        self.assertEqual(result['release_gate']['status'], 'coordinate_contract_passed')
        self.assertEqual(result['final_code'], '<html>new</html>')
        self.assertEqual([item['status'] for item in result['downstream_history']], [
            'invalidated_by_upstream_change', 'active'])
        self.assertEqual(len(result['attempts']), 2)
        self.assertEqual(result['attempts'][0]['raw_response'], 'first-raw')

    def test_baseline_same_first_attempt_detects_and_stops_without_repair(self):
        state, _ = fixture(); calls = []
        graph = build_ui_feedback_graph(lambda **kwargs: calls.append(kwargs),
                                        lambda value: '<html>unexpected</html>', allow_repair=False)
        result = graph.invoke(state)
        self.assertEqual(calls, [])
        self.assertEqual(result['release_gate']['status'], 'blocked')
        self.assertIsNone(result['final_code'])
        self.assertEqual(result['attempts'][0]['raw_response'], 'first-raw')

    def test_first_attempt_pass_does_not_force_repair(self):
        state, repair = fixture(); state['attempts'] = [copy.deepcopy(repair)]
        state['attempts'][0]['attempt_id'] = 'architect-0'; calls = []
        graph = build_ui_feedback_graph(lambda **kwargs: calls.append(kwargs),
                                        lambda value: '<html>valid</html>', allow_repair=True)
        result = graph.invoke(state)
        self.assertEqual(calls, [])
        self.assertEqual(len(result['attempts']), 1)
        self.assertEqual(result['release_gate']['status'], 'coordinate_contract_passed')

    def test_repair_changing_immutable_text_is_rejected(self):
        state, repair = fixture(); repair['parsed']['elements'][0]['text'] = 'Changed'
        graph = build_ui_feedback_graph(lambda **kwargs: copy.deepcopy(repair),
                                        lambda value: '<html>unexpected</html>', allow_repair=True)
        result = graph.invoke(state)
        self.assertEqual(result['release_gate']['status'], 'blocked')
        self.assertIsNone(result['final_code'])
        regression = result['quality_history'][-1]['regression']
        self.assertEqual(regression['changes'][0]['field'], 'text')

    def test_repair_cannot_change_unreported_derivation(self):
        state, repair = fixture()
        repair['parsed']['elements'][0]['spatial_info']['derivation']['reason'] = 'changed unrelated reason'
        graph = build_ui_feedback_graph(lambda **kwargs: copy.deepcopy(repair),
                                        lambda value: '<html>unexpected</html>', allow_repair=True)
        result = graph.invoke(state)
        self.assertEqual(result['release_gate']['status'], 'blocked')
        fields = [item['field'] for item in result['quality_history'][-1]['regression']['changes']]
        self.assertIn('spatial_info.derivation.reason', fields)

    def test_bbox_permission_is_scoped_to_failed_object(self):
        state, repair = fixture()
        second = copy.deepcopy(state['attempts'][0]['parsed']['elements'][0])
        second.update(id='e2', vision_id='e2', text='Other')
        second['spatial_info']['bbox'] = [400, 100, 600, 180]
        state['vision_elements']['elements'].append({
            'id':'e2','type':'button','text':'Other',
            'bbox':{'x_min':.3,'y_min':.1,'x_max':.4,'y_max':.2}})
        state['attempts'][0]['parsed']['elements'].append(copy.deepcopy(second))
        repair['parsed']['elements'].append(copy.deepcopy(second))
        repair['parsed']['elements'][1]['spatial_info']['bbox'] = [500, 100, 700, 180]
        graph = build_ui_feedback_graph(lambda **kwargs: copy.deepcopy(repair),
                                        lambda value: '<html>unexpected</html>', allow_repair=True)
        result = graph.invoke(state)
        changes = result['quality_history'][-1]['regression']['changes']
        self.assertIn({'object_id':'e2','field':'spatial_info.bbox',
                       'before':[400,100,600,180],'after':[500,100,700,180]}, changes)

    def test_evidence_ref_permission_does_not_allow_derivation_reason_change(self):
        state, repair = fixture()
        state['attempts'][0]['parsed']['elements'][0]['spatial_info']['bbox'] = [100,100,300,180]
        state['attempts'][0]['parsed']['elements'][0]['spatial_info']['derivation']['evidence_refs'] = [
            'vision:does_not_exist']
        repair['parsed']['elements'][0]['spatial_info']['derivation']['reason'] = 'changed reason'
        graph = build_ui_feedback_graph(lambda **kwargs: copy.deepcopy(repair),
                                        lambda value: '<html>unexpected</html>', allow_repair=True)
        result = graph.invoke(state)
        fields = [item['field'] for item in result['quality_history'][-1]['regression']['changes']]
        self.assertIn('spatial_info.derivation.reason', fields)


if __name__ == '__main__':
    unittest.main()
