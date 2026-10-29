import copy
import unittest
from src.utils.composite_input_layout import compile_composite

def fixture(height=120):
    es=[{'id':'body','type':'input','text':'','rpa_action':'edit','spatial_info':{'bbox':[0,0,200,height]}},
        {'id':'tool','type':'button','text':'+','rpa_action':'attach','spatial_info':{'bbox':[0,height-44,44,height]}}]
    s={'page_meta':{'viewport':{'width':200,'height':200}},'elements':es}
    c={'status':'supported','region':{'bbox':[0,0,200,height],'input_id':'body','tools':[{'id':'tool','horizontal_anchor':'left','vertical_anchor':'bottom','order':0,'quote':'left tool'}]}}
    return s,c

class TestComposite(unittest.TestCase):
    def test_compile_without_mutation(self):
        s,c=fixture();old=copy.deepcopy(s);r=compile_composite(s,s,c,'left tool')
        self.assertEqual(s,old);self.assertEqual(r['elements'][0]['spatial_info']['bbox'],[0,0,200,68])
        for a,b in zip(s['elements'],r['elements']):
            for k in ('id','type','text','rpa_action'):self.assertEqual(a[k],b[k])
    def test_72_cannot_fit_96(self):
        s,c=fixture(72)
        with self.assertRaisesRegex(ValueError,'UNSAT_HEIGHT'):compile_composite(s,s,c,'left tool')
    def test_unknown_no_inference(self):
        s,c=fixture();c['status']='unknown'
        with self.assertRaisesRegex(ValueError,'RELATION_UNKNOWN'):compile_composite(s,s,c,'left tool')
    def test_no_fake_quote(self):
        s,c=fixture()
        with self.assertRaisesRegex(ValueError,'SOURCE_QUOTE'):compile_composite(s,s,c,'different')
    def test_no_unobserved_member(self):
        s,c=fixture();c['region']['tools'][0]['id']='missing'
        with self.assertRaisesRegex(ValueError,'UNKNOWN_OR_DUPLICATE'):compile_composite(s,s,c,'left tool')

if __name__=='__main__':unittest.main()
