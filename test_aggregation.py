import unittest
from aggregate import aggregate
from worker import allocation


def fixture(count=20, same_origin=False, disjoint=False):
    result = []
    for worker in range(count):
        start = worker * 100 if disjoint else 0
        result.append({'shard': worker, 'shards': 20, 'start_epoch': 100,
                       'profile': [[1000, 100]], 'completed': True,
                       'last_observed': start + 100,
                       'origin_ip': '192.0.2.1' if same_origin else f'192.0.2.{worker+1}',
                       'errors': [], 'navigation': [],
                       'intervals': [{'start': start, 'end': start + 100} for _ in range(50)]})
    return result


class EvidenceTests(unittest.TestCase):
    def test_verified_overlap(self):
        result = aggregate(fixture())
        self.assertEqual(result['observed_peak_active_browser_sessions'], 1000)
        self.assertTrue(result['qualified_pass']['1000'])

    def test_missing_workers_cannot_pass(self):
        result = aggregate(fixture(10))
        self.assertEqual(result['observed_peak_active_browser_sessions'], 500)
        self.assertFalse(result['qualified_pass']['1000'])

    def test_same_network_does_not_prove_distributed_test(self):
        self.assertFalse(aggregate(fixture(same_origin=True))['qualified_pass']['1000'])

    def test_nonoverlapping_sessions_are_not_simultaneous(self):
        result = aggregate(fixture(disjoint=True))
        self.assertEqual(result['observed_peak_active_browser_sessions'], 50)
        self.assertFalse(result['qualified_pass']['1000'])

    def test_open_intervals_end_at_last_observation(self):
        records = fixture()
        for record in records:
            record['last_observed'] = 10
            for interval in record['intervals']:
                interval['end'] = None
        self.assertFalse(aggregate(records)['qualified_pass']['1000'])

    def test_uneven_allocation(self):
        self.assertEqual(sum(allocation(250, i, 20) for i in range(20)), 250)
        self.assertEqual(sum(allocation(2000, i, 20) for i in range(20)), 2000)


if __name__ == '__main__':
    unittest.main()
