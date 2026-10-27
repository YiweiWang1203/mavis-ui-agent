import copy
import os
import unittest
from unittest.mock import patch
from html.parser import HTMLParser
from src.renderers.controlled_components import render_controlled_components
from src.agents import coder

class Collector(HTMLParser):
    def __init__(self):
        super().__init__();self.nodes={}
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if 'id' in a:self.nodes[a['id']]=(tag,a)

class ControlledTests(unittest.TestCase):
    def state(self):
        return {'page_meta':{'viewport':{'width':375,'height':812},'locale':'zh-CN','layout_solver':{'version':'hierarchy-v1'}},'elements':[
            {'id':'region','type':'card','spatial_info':{'bbox':[0,500,375,700]}},
            {'id':'query','type':'search_bar','spatial_info':{'bbox':[10,20,210,60]}},
            {'id':'send','type':'button','text':'Send','parent_id':'region','spatial_info':{'bbox':[20,580,150,620]}}]}
    def test_native_controls_keep_global_geometry_and_semantic_parent(self):
        s=self.state();old=copy.deepcopy(s);code=render_controlled_components(s);p=Collector();p.feed(code)
        self.assertEqual(p.nodes['query'][0],'input')
        self.assertEqual(p.nodes['query'][1]['type'],'search')
        self.assertEqual(p.nodes['send'][0],'button')
        self.assertEqual(p.nodes['send'][1]['data-parent-id'],'region')
        self.assertIn('top:580px',p.nodes['send'][1]['style'])
        self.assertIn('min-height:0',code)
        self.assertEqual(s,old)
    def test_text_and_ids_are_not_executable_html_or_js(self):
        s=self.state();s['elements'][2]['text']='</script><img src=x onerror=alert(1)>'
        code=render_controlled_components(s);p=Collector();p.feed(code)
        self.assertIn('&lt;/script&gt;',code)
        self.assertNotIn('<img src=x',code)
        self.assertEqual(p.nodes['send'][1]['data-intent-label'],s['elements'][2]['text'])
    def test_explicit_readonly_and_disabled_are_preserved(self):
        s=self.state();s['elements'][1]['readonly']=True;s['elements'][2]['disabled']=True
        p=Collector();p.feed(render_controlled_components(s))
        self.assertIn('readonly',p.nodes['query'][1]);self.assertIn('disabled',p.nodes['send'][1])
    def test_reserved_root_and_invalid_geometry_fail(self):
        s=self.state();s['elements'][0]['id']='page-root'
        with self.assertRaises(ValueError):render_controlled_components(s)
        s=self.state();s['elements'][2]['spatial_info']['bbox']=[0,0,0,0]
        with self.assertRaises(ValueError):render_controlled_components(s)
    def test_real_generation_path_does_not_call_coder_model(self):
        with patch.dict(os.environ,{'UI_RENDERER_MODE':'controlled_components_v1','UI_CODER_CONTRACT_MODE':'controlled_components_v1','UI_INPUT_CONTRACT_MODE':'off'}),patch.object(coder,'_get_openai_client') as model,patch.object(coder,'save_html_asset',return_value=None):
            r=coder.generate_frontend_code(self.state())
        model.assert_not_called()
        self.assertEqual(r['renderer'],'controlled_components_v1')
        self.assertIn('addEventListener',r['code'])
        self.assertIn('button[data-intent-label]',r['code'])

if __name__=='__main__':unittest.main()
