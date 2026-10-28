import unittest
from scripts.run_semantic_plan_comparison import realized_accounting


class RealizedAccountingTests(unittest.TestCase):
    def test_failed_first_call_does_not_become_three_calls_or_free_tokens(self):
        result = realized_accounting([{'status': 'failed', 'http_status': 500}], [], True)
        self.assertEqual(result['physical_attempts'], 1)
        self.assertEqual(result['returned_calls'], 0)
        self.assertEqual(result['candidate_exclusive_attempts'], 0)
        self.assertFalse(result['candidate_stage_attempted'])
        self.assertFalse(result['usage_complete'])
        self.assertIsNone(result['total_tokens_if_known'])
        self.assertFalse(result['billing_cost_known'])

    def test_shared_effective_cost_not_double_counted(self):
        call = lambda n: {'status': 'returned', 'response': {'usage': {'total_tokens': n}}}
        result = realized_accounting([call(100), call(200)], [call(50)], True)
        self.assertEqual(result['physical_attempts'], 3)
        self.assertEqual(result['baseline_effective_attempts'], 2)
        self.assertEqual(result['candidate_effective_attempts'], 3)
        self.assertEqual(result['total_tokens_if_known'], 350)
        self.assertTrue(result['usage_complete'])
