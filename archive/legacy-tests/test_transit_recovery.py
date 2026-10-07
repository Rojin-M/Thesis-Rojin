import unittest
from types import SimpleNamespace

import numpy as np

from scripts.experiments.transit_recovery import (
    aperture_samples, exact_score_threshold, select_count_threshold, single_event_search,
)


class TransitRecoveryTests(unittest.TestCase):
    def test_weak_single_transit_and_linear_trend(self):
        rng = np.random.default_rng(11)
        time = np.arange(0, 20, 1 / 720)
        flux = 1 + .001 * time + rng.normal(0, .0005, len(time))
        flux[np.abs(time - 10) < 2 / 48] -= .0005
        events = single_event_search(time, flux, [.5, 1, 2, 4], minimum_score=5)
        self.assertTrue(any(abs(e['center_btjd'] - 10) < 1 / 24 for e in events))

    def test_long_single_transit(self):
        rng = np.random.default_rng(2)
        time = np.arange(0, 20, 1 / 720)
        flux = 1 + rng.normal(0, .0002, len(time))
        flux[np.abs(time - 10) < 10 / 48] -= .001
        events = single_event_search(time, flux, [2, 4, 8, 10, 12], minimum_score=5)
        near = [e for e in events if abs(e['center_btjd'] - 10) < 2 / 24]
        self.assertEqual(len(near), 1)
        self.assertGreaterEqual(near[0]['duration_hours'], 8)

    def test_gap_is_not_a_dip(self):
        time = np.arange(0, 10, 1 / 720)
        keep = np.abs(time - 5) > .3
        events = single_event_search(time[keep], np.ones(keep.sum()), [1, 4, 8])
        self.assertEqual(events, [])

    def test_incomplete_aperture_rejected(self):
        cube = np.ones((1000, 2, 2))
        cube[500, 0, 0] = np.nan
        pixels = SimpleNamespace(flux=cube, time=np.arange(1000) / 720,
                                 aperture=np.full((2, 2), 2), quality=np.zeros(1000))
        time, flux = aperture_samples(pixels)
        self.assertEqual(len(time), 999)
        self.assertTrue(np.all(flux == 1))

    def test_exact_boundary_and_ties(self):
        events = [[{'score': 51., 'count': 10}, {'score': 80., 'count': 1}]] + [[] for _ in range(99)]
        result = exact_score_threshold(events, [27.] * 100, .1, margin=1.)
        self.assertGreater(result['selected_threshold'], 51.)
        self.assertLess(result['selected_threshold'], 80.)
        self.assertEqual(result['selected']['events'], 1)

    def test_nonmonotone_neural_event_counts(self):
        counts = np.zeros((4, 100), dtype=int)
        counts[0, :50] = 1
        counts[2, :50] = 1
        result = select_count_threshold([.5, .6, .7, 1.01], counts, [27.] * 100, .2, margin=1)
        self.assertEqual(result['selected_threshold'], 1.01)

    def test_insufficient_exposure_fails_closed(self):
        with self.assertRaisesRegex(ValueError, 'Insufficient calibration'):
            exact_score_threshold([[], []], [1., 1.], 1.)

    def test_invalid_times_and_nonfinite_scores(self):
        with self.assertRaises(ValueError):
            single_event_search(np.ones(300), np.ones(300), [1])
        with self.assertRaises(ValueError):
            exact_score_threshold([[{'score': float('nan')}], []], [27., 27.], 1.)


if __name__ == '__main__':
    unittest.main()
