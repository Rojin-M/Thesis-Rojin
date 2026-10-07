import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.experiments.ai_telescope_recovery import METHODS, finish, recovery_rows, validate_config
from scripts.research.protocol import ROOT


class RecoveryExperimentTests(unittest.TestCase):
    def test_output_cannot_overwrite_baseline(self):
        config = json.loads((ROOT / 'configs/ai_telescope_recovery_v1.json').read_text())
        config['output'] = config['baseline_run']
        with self.assertRaisesRegex(ValueError, 'overlaps'):
            validate_config(config)

    def test_incremental_report_preserves_unobservable_hosts(self):
        rows = []
        for index, (mode, depth) in enumerate(zip(['single', 'periodic', 'ttv'], [.0005, .001, .002])):
            rows.append({'target_id': str(index), 'exposure_days': 27.,
                         'truth': {'mode': mode, 'depth': depth, 'duration_hours': 2.,
                                   'observed_centers_btjd': [3., 6.] if index else []},
                         'cases': {case: {m: {'centers_btjd': [3., 6.] if case == 'injected' else [3.]}
                                          for m in METHODS} for case in ['original', 'injected', 'inverted']}})
        flat = recovery_rows(rows)
        self.assertEqual(sum(r['incremental_events'] for r in flat), 2 * len(METHODS))
        spec = {'physical_config': {'modes': ['single', 'periodic', 'ttv'], 'depths': [.0005, .001, .002]},
                'config': {'control_budget_per_27_days': 1}}
        with tempfile.TemporaryDirectory() as folder:
            with patch('builtins.print'):
                finish(rows, spec, 'test-sha', {}, Path(folder))
            summary = json.loads((Path(folder) / 'summary.json').read_text())
            self.assertEqual(summary['registered_hosts'], 3)
            self.assertEqual(summary['observable_hosts'], 2)
            self.assertEqual(summary['methods']['hybrid']['incremental_hosts'], 2)
            self.assertTrue((Path(folder) / 'complete.json').is_file())


if __name__ == '__main__':
    unittest.main()
