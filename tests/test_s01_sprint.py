import unittest
from scripts.run_s01_sprint import routing_kwargs,FLAGS
class S01Contract(unittest.TestCase):
 def test_stage_routing_and_fixed_budget(self):
  original={'model':'wrong','max_tokens':3,'messages':[{'role':'user','content':'same'}]}
  got=routing_kwargs('coder',original,{'coder':'chosen'})
  self.assertEqual(got['model'],'chosen');self.assertEqual(got['max_tokens'],8192)
  self.assertEqual(got['messages'],original['messages']);self.assertEqual(original['max_tokens'],3)
 def test_unknown_stage_stops(self):
  with self.assertRaises(ValueError):routing_kwargs('automatic_repair',{}, {'coder':'chosen'})
 def test_no_silent_renderer_or_new_mechanism(self):
  self.assertEqual(FLAGS['UI_RENDERER_MODE'],'llm');self.assertEqual(FLAGS['UI_STRUCTURE_MODE'],'baseline')
  self.assertEqual(FLAGS['UI_FUSION_MODE'],'exact_id');self.assertEqual(FLAGS['UI_INPUT_CONTRACT_MODE'],'off')
if __name__=='__main__':unittest.main()
