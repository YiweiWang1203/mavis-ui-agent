import unittest
from src.utils.source_region_slots import inventory_slots, bind_regions


class SourceRegionSlotsTest(unittest.TestCase):
    def setUp(self):
        self.declaration = {'regions': [{'id': 'r1', 'name': 'composer', 'source_quote': 'bottom editor'}]}
        self.slots = inventory_slots(self.declaration, 'Use a bottom editor here.')
        self.binding = {'bindings': [{'region_id': 'r1', 'bbox': [.1, .7, .9, .9], 'visual_evidence': 'outlined lower area'}]}

    def test_source_offsets(self):
        self.assertEqual('Use a bottom editor here.'[self.slots[0]['source_start']:self.slots[0]['source_end']], 'bottom editor')

    def test_nonverbatim_or_ambiguous_source_rejected(self):
        for source in ['editor at bottom', 'bottom editor and bottom editor']:
            with self.assertRaises(ValueError): inventory_slots(self.declaration, source)

    def test_duplicate_and_reserved_slots_rejected(self):
        for rows in [self.declaration['regions'] * 2, [{'id': 'page', 'name': 'x', 'source_quote': 'bottom editor'}]]:
            with self.assertRaises(ValueError): inventory_slots({'regions': rows}, 'bottom editor')

    def test_missing_unknown_duplicate_bindings_rejected(self):
        for rows in [[], self.binding['bindings'] * 2, [{'region_id': 'r2', 'bbox': None, 'visual_evidence': 'not found'}]]:
            with self.assertRaises(ValueError): bind_regions(self.slots, {'bindings': rows})

    def test_invalid_box_not_repaired(self):
        for box in [[0, 0, 1000, 1000], [0, 1, .5, .3], [0, 0, float('nan'), 1], [False, 0, 1, 1]]:
            with self.assertRaises(ValueError):
                bind_regions(self.slots, {'bindings': [{**self.binding['bindings'][0], 'bbox': box}]})

    def test_unresolved_retained(self):
        result = bind_regions(self.slots, {'bindings': [{**self.binding['bindings'][0], 'bbox': None}]})
        self.assertEqual((result['localized_count'], result['unresolved_count']), (0, 1))
        self.assertEqual(result['regions'][0]['parent_id'], 'page')

    def test_empty_is_not_localized_coverage(self):
        self.assertEqual(bind_regions([], {'bindings': []})['localized_count'], 0)


if __name__ == '__main__': unittest.main()
