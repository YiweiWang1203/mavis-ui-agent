import unittest
from src.utils.candidate_blind_observation import match_observation


def proposal(*boxes):
    return {'candidates': [dict(id=str(i), quad=[[a,b],[c,b],[c,d],[a,d]], source_line_ids=['observed']) for i,(a,b,c,d) in enumerate(boxes)]}


def observation(box, uncertain=False):
    return dict(page_bbox=box, visible_ui_evidence='Visible outer UI, including its lower controls', uncertain=uncertain)


class ObservationTests(unittest.TestCase):
    def test_select_existing_geometry_and_keep_evidence(self):
        p=proposal((10,10,90,70),(10,10,90,90))
        r=match_observation(p,observation([.1,.1,.9,.9]),100,100)
        self.assertEqual(r['id'],'1');self.assertEqual(r['quad'],p['candidates'][1]['quad'])
        self.assertEqual(r['source_line_ids'],['observed'])

    def test_near_tie_unresolved_independent_of_order(self):
        p=proposal((10,10,90,90),(10,10,90,89))
        for rows in (p['candidates'],list(reversed(p['candidates']))):
            self.assertEqual(match_observation({'candidates':rows},observation([.1,.1,.9,.9]),100,100)['status'],'unresolved')

    def test_no_matching_candidate_does_not_create_boundary(self):
        self.assertIsNone(match_observation(proposal((10,10,90,50)),observation([.1,.1,.9,.9]),100,100)['quad'])

    def test_bad_units_and_incomplete_contract_rejected(self):
        for d in [observation([100,100,900,900]),observation([0,0,float('nan'),1]),{'page_bbox':[0,0,1,1]}]:
            with self.assertRaises(ValueError):match_observation(proposal((0,0,100,100)),d,100,100)

    def test_uncertainty_and_empty_candidates(self):
        self.assertEqual(match_observation(proposal(),observation([0,0,1,1]),100,100)['status'],'unresolved')
        self.assertEqual(match_observation(proposal(),observation(None,True),100,100)['status'],'unresolved')


if __name__=='__main__':unittest.main()
