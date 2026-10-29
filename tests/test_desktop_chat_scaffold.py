import copy
import unittest
from src.agents.desktop_chat_scaffold import ROLES,compile_desktop_chat
from src.agents.frozen_region_planner import frozen_inventory
from tests.test_projection_flow_layout import ProjectionFlowTests as _Fixtures
from src.utils.text_evidence_contract import source_spans

fixture=_Fixtures().fixture
del _Fixtures


class DesktopChatScaffoldTests(unittest.TestCase):
    def fixture(self):
        state,vision,kw=fixture(); exemplar=state['elements'][0]; ve=vision['elements'][0]
        state['elements']=[];vision['elements']=[]
        for i,role in enumerate(ROLES):
            eid='entity_'+str(i);e=copy.deepcopy(exemplar);v=copy.deepcopy(ve)
            e.update(id=eid,vision_id=eid,type='input' if role=='composer_input' else 'button',text=role,parent_id=None,
                source_refs=[{'source':'vision','id':eid}])
            v.update(id=eid,type=e['type'],text=role)
            state['elements'].append(e);vision['elements'].append(v)
        kw.update(request='电脑聊天页面',speech='左侧历史和个人信息，右侧会话，底部输入及附件语音发送',viewport={'id':'desktop','width':1440,'height':900})
        ref=source_spans({'request':kw['request'],'speech':kw['speech']})[-1]['ref']
        binding={'roles':{role:{'entity_ids':['entity_'+str(i)],'evidence_refs':[ref]} for i,role in enumerate(ROLES)},'unresolved':[]}
        return binding,state,vision,kw

    def test_complete_identity_and_regions(self):
        b,s,v,k=self.fixture();before=copy.deepcopy(s);out=compile_desktop_chat(b,s,v,**k)
        self.assertEqual(s,before);self.assertEqual(frozen_inventory(out),frozen_inventory(s))
        es={e['id']:e for e in out['elements']}
        for i in range(4):self.assertLessEqual(es['entity_'+str(i)]['spatial_info']['bbox'][2],360)
        for i in range(4,9):self.assertGreaterEqual(es['entity_'+str(i)]['spatial_info']['bbox'][0],360)
        input_box=es['entity_5']['spatial_info']['bbox'];tool_box=es['entity_6']['spatial_info']['bbox']
        self.assertLessEqual(input_box[3],tool_box[1]);self.assertEqual(input_box[2]-input_box[0],1048)
        self.assertTrue(out['page_meta']['desktop_chat_scaffold']['proportions_are_design_defaults'])
        self.assertFalse(out['page_meta']['desktop_chat_scaffold']['dom_nesting_implied'])

    def test_duplicate_unknown_missing_or_unresolved_rejected(self):
        for which in ['duplicate','unknown','missing','unresolved','empty','extra']:
            b,s,v,k=self.fixture()
            if which=='duplicate':b['roles']['search']['entity_ids']=['entity_0']
            if which=='unknown':b['roles']['search']['entity_ids']=['unknown']
            if which=='missing':b['roles'].pop('profile')
            if which=='unresolved':b['unresolved']=['entity_0']
            if which=='empty':b['roles']['send']['entity_ids']=[]
            if which=='extra':b['roles']['send']['bbox']=[0,0,1,1]
            with self.assertRaises(ValueError):compile_desktop_chat(b,s,v,**k)

    def test_native_input_and_declared_device_required(self):
        b,s,v,k=self.fixture();s['elements'][5]['type']='text'
        with self.assertRaises(ValueError):compile_desktop_chat(b,s,v,**k)
        b,s,v,k=self.fixture();k['request']='手机聊天'
        with self.assertRaises(ValueError):compile_desktop_chat(b,s,v,**k)

    def test_source_refs_not_free_quotes(self):
        b,s,v,k=self.fixture();b['roles']['profile']['evidence_refs']=['invented:s1']
        with self.assertRaises(ValueError):compile_desktop_chat(b,s,v,**k)

    def test_multiple_conversation_objects_retained(self):
        b,s,v,k=self.fixture();extra=copy.deepcopy(s['elements'][4]);extra.update(id='message2',vision_id='message2')
        extra['source_refs']=[{'source':'vision','id':'message2'}]
        observed=copy.deepcopy(v['elements'][4]);observed['id']='message2'
        s['elements'].append(extra);v['elements'].append(observed);b['roles']['conversation']['entity_ids'].append('message2')
        out=compile_desktop_chat(b,s,v,**k);self.assertEqual(len(out['elements']),10)
