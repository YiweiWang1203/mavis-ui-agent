import unittest
from src.utils.page_content_guard import guard_selection


def evidence(points, uncertain=False):
    return dict(regions=[dict(id=str(i), name='visible UI region', point=p, visual_evidence='visible ink and controls') for i,p in enumerate(points)], uncertain=uncertain)


class ContentGuardTests(unittest.TestCase):
    def setUp(self):
        self.proposals={'candidates':[dict(id='short',quad=[[10,10],[90,10],[90,70],[10,70]]),dict(id='full',quad=[[10,10],[90,10],[90,90],[10,90]])]}

    def run_guard(self,points,selected='short',uncertain=False):
        return guard_selection(self.proposals,dict(candidate_id=selected,unresolved_reason=None),evidence(points,uncertain),100,100)

    def test_outside_ui_veto_with_side_and_no_auto_reselection(self):
        r=self.run_guard([[.5,.5],[.5,.8]])
        self.assertIsNone(r['quad']);self.assertEqual(r['outside_region_ids'],['1'])
        self.assertEqual(r['content_audit'][0]['points'][1]['outside_sides'],['bottom'])
        self.assertTrue(r['content_audit'][1]['compatible_with_observed_points'])
        hint=r['correction_hints'][0]
        self.assertEqual(hint['side'],'bottom')
        self.assertEqual(hint['outward_unit_vector'],[0,1])
        self.assertEqual(hint['minimum_parallel_outward_shift_to_include_observed_points_pixels'],10)

    def test_valid_selection_preserves_original_geometry(self):
        r=self.run_guard([[.5,.5],[.5,.8]],'full')
        self.assertEqual(r['quad'],self.proposals['candidates'][1]['quad'])
        self.assertEqual(r['content_guard_status'],'not_refuted_by_observed_points')

    def test_empty_and_uncertain_never_pass(self):
        self.assertIsNone(self.run_guard([])['quad'])
        self.assertIsNone(self.run_guard([[.5,.5]],uncertain=True)['quad'])

    def test_bad_units_and_duplicate_ids_fail(self):
        with self.assertRaises(ValueError):self.run_guard([[500,800]])
        d=evidence([[.5,.5],[.6,.6]]);d['regions'][1]['id']='0'
        with self.assertRaises(ValueError):guard_selection(self.proposals,dict(candidate_id='short',unresolved_reason=None),d,100,100)

    def test_winding_and_boundary_do_not_change_containment(self):
        for row in self.proposals['candidates']:row['quad']=list(reversed(row['quad']))
        self.assertIsNotNone(self.run_guard([[.5,.7]])['quad'])


if __name__=='__main__':unittest.main()
