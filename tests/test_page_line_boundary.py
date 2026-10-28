import unittest
from src.utils.page_line_boundary import compile_boundary


class BoundaryTests(unittest.TestCase):
    def fixture(self):
        points=[[10,30,90,30],[90,30,90,80],[90,80,10,80],[10,80,10,30]]
        lines=[{'id':str(i),'endpoints':p} for i,p in enumerate(points)]
        choice={'side_ids':dict(zip(['top','right','bottom','left'],['0','1','2','3'])),'unresolved_reason':None}
        return lines,choice

    def test_supported_quad_mapping(self):
        lines,choice=self.fixture();r=compile_boundary(lines,choice,100,100)
        self.assertEqual(r['bbox'],[.1,.3,.9,.8]);self.assertEqual(r['area_fraction'],.4)

    def test_unresolved_is_not_full_image_fallback(self):
        r=compile_boundary([],{'side_ids':None,'unresolved_reason':'cut off'},100,100)
        self.assertIsNone(r['quad'])

    def test_unknown_duplicate_parallel_rejected(self):
        for mode in ['unknown','duplicate','parallel']:
            lines,c=self.fixture()
            if mode=='unknown':c['side_ids']['left']='missing'
            if mode=='duplicate':c['side_ids']['left']='0'
            if mode=='parallel':lines[1]['endpoints']=[10,40,90,40]
            with self.assertRaises(ValueError):compile_boundary(lines,c,100,100)


if __name__=='__main__':unittest.main()
