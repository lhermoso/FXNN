import unittest
import numpy as np
from fxnn.meta_dataset import project, verify_projection_source


def source_fixture():
    n = 496
    closes = np.full(n, '1.0000', dtype='<U20')
    breaks = np.zeros(n, bool)
    selected = np.arange(61, n, 62)
    for i, value in zip(selected, ('1.0100', '.9900', '1.0000', '1.0100', '1.0100', '.9900', '1.0100', '.9900')):
        breaks[i-61] = True
        closes[i-1] = value
    stamps = np.arange(n, dtype=np.int64)*60+1641214800
    observed = dict(stamps=stamps, original_indices=np.arange(n)+10000, closes=closes, breaks=breaks,
                    X=np.column_stack((np.arange(n)/n, np.ones(n))), causal_valid=np.ones(n, bool),
                    eligibility_reason=np.full(n, 'eligible', dtype='<U24'),
                    cusum_0=np.ones(n, bool))
    observed['cusum_0.0005'] = np.ones(n, bool)
    observed['cusum_0.001'] = np.ones(n, bool)
    del observed['cusum_0']
    observed['causal_valid'][selected[3]] = False
    observed['eligibility_reason'][selected[3]] = 'vol_history'
    for h in ('0.0005', '0.001'):
        observed['cusum_'+h][selected[4]] = False
    entry = np.repeat(np.arange(n), 2)
    candidates = dict(entry_local=entry, entry_indices=observed['original_indices'][entry],
                      starts=stamps[entry], sides=np.tile([1, -1], n), ends=stamps[entry]+60,
                      info_ends=stamps[entry]+240, last_information_bar_end=stamps[entry]+60,
                      outcomes=np.full(2*n, 'stop_loss', dtype='<U24'))
    for i, side, outcome in zip(selected, (1, -1, 0, 1, 1, -1, 1, -1),
                               ('take_profit', 'censored', 'stop_loss', 'stop_loss', 'stop_loss', 'ambiguous', 'take_profit', 'boundary')):
        if side:
            candidates['outcomes'][2*i+int(side == -1)] = outcome
    candidates['outcomes'][2*selected[1]] = 'take_profit'
    schema = dict(feature_names=['movement', 'direction'], feature_groups={'movement': [0], 'context': [1]}, directional_features=[0])
    return observed, candidates, schema, selected


class MetaDatasetTests(unittest.TestCase):
    def test_unilateral_bundle_preserves_full_horizon_and_observed_buffer(self):
        from datetime import datetime, timezone
        from fxnn.meta_dataset import make_bundle
        from fxnn.session_clock import SessionClock
        n, origin = 20000, 1641214800
        stamps = origin + np.arange(n, dtype=np.int64)*60
        clock = SessionClock(origin, np.ones(n+5000, dtype=bool))
        observed = dict(stamps=stamps, original_indices=np.arange(n)+500,
            closes=np.asarray([str(1+i/100000) for i in range(n)]),
            breaks=np.zeros(n, bool), X=np.ones((n, 2)), causal_valid=np.ones(n, bool),
            eligibility_reason=np.full(n, 'eligible'),
            **{f'cusum_{h}': np.arange(n) % 3 == 0 for h in (.0005, .001)})
        entry = np.repeat(np.arange(n), 2)
        candidates = dict(entry_local=entry, entry_indices=observed['original_indices'][entry],
            starts=stamps[entry], sides=np.tile([1, -1], n), ends=stamps[entry]+60,
            info_ends=clock.deadlines(stamps[entry]), last_information_bar_end=stamps[entry]+60,
            outcomes=np.where(entry % 2, 'take_profit', 'stop_loss'))
        def date(i):
            return datetime.fromtimestamp(origin+i*60, timezone.utc).isoformat()
        protocol = dict(development=[date(0), date(n)], folds=[dict(name='fixture',
            validation_start=date(10000), test_start=date(15000), test_end=date(n))])
        schema = dict(feature_names=['movement', 'direction'],
            feature_groups={'movement': [0], 'context': [1]}, directional_features=[0])
        bundle = make_bundle(observed, candidates, schema, protocol, clock)
        parts, data = bundle['partitions']['fixture'], bundle['data']
        # Independent arithmetic on this all-open synthetic clock: an early exit
        # does not shorten 4320 minutes of information or the 1941-observation buffer.
        for part, first, stop in [('train', 61, 10000-1941-4320),
                                 ('refit', 61, 15000-1941-4320),
                                 ('validation', 10000, 15000-4320),
                                 ('test', 15000, n-4320)]:
            np.testing.assert_array_equal(data.entry_indices[parts[part]]-500,
                                          np.arange(first, stop))
        self.assertEqual(bundle['opportunities']['side'][-1], 1)
        self.assertNotIn(len(data.y)-1, parts['test'])

    def test_projection_orientation_and_selected_censoring(self):
        observed, candidates, schema, selected = source_fixture()
        data, op, rows = project(observed, candidates, schema)
        np.testing.assert_array_equal(op['side'][selected], [1, -1, 0, 1, 1, -1, 1, -1])
        self.assertEqual(op['outcomes'][selected[1]], 'censored')
        self.assertEqual(op['candidate_rows'][selected[2]], -1)
        self.assertEqual(op['outcomes'][selected[2]], 'no_primary_signal')
        self.assertEqual(op['X'][selected[1], 0], -observed['X'][selected[1], 0])
        self.assertNotIn(selected[1], rows)
        self.assertIn(selected[6], rows)  # Future partition exclusion is separate.
        order = np.arange(len(candidates['starts']))[::-1]
        shuffled = {k: v[order] for k, v in candidates.items()}
        other, projected, _ = project(observed, shuffled, schema)
        np.testing.assert_array_equal(other.X, data.X)
        np.testing.assert_array_equal(projected['outcomes'], op['outcomes'])

    def test_bilateral_crosscheck_catches_orientation_regression(self):
        observed, candidates, schema, _ = source_fixture()
        data, op, rows = project(observed, candidates, schema)
        source = {k: getattr(data, k).copy() for k in ('X', 'y', 'starts', 'ends', 'info_ends', 'entry_indices', 'sides')}
        source['candidate_rows'] = op['candidate_rows'][rows]
        bundle = dict(data=data, opportunities=op, opening_rows=rows)
        verify_projection_source(bundle, source)
        source['X'][0, 0] += 1
        with self.assertRaises(AssertionError):
            verify_projection_source(bundle, source)

    def test_exclusive_artifacts_and_projection_replay(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from unittest.mock import patch
        import hashlib
        from fxnn import meta_dataset as module
        from fxnn.experiment_fit import StageLedger
        from fxnn.session_clock import weekly_fx_clock
        observed, candidates, schema, _ = source_fixture()
        data, op, selected = project(observed, candidates, schema)
        source_data = {name: getattr(data, name) for name in module.FIELDS}
        source_data['candidate_rows'] = op['candidate_rows'][selected]
        source_manifest = {'schema': schema}
        clock = weekly_fx_clock(int(observed['stamps'][0])-86400, int(observed['stamps'][-1])+86400)
        with TemporaryDirectory() as tmp:
            root = Path(tmp); source = root/'source'; source.mkdir()
            (source/'manifest.json').write_text('{}')
            config, protocol = root/'config.json', root/'protocol.md'
            config.write_text('{}'); protocol.write_text('fixture')
            ledger = StageLedger(root/'ledger', 7); ledger.initialize(0, 'fixture')
            before = ledger.path.read_bytes()
            spec = dict(global_ledger=str(ledger.path), expected_prior_fits=0,
                        ledger_before_sha256=hashlib.sha256(before).hexdigest(),
                        source_dataset_manifest_sha256=module.digest(source/'manifest.json'))
            output = root/'projection'
            with patch.object(module, 'SPEC', config), patch.object(module, 'CONTRACT', protocol), \
                    patch.object(module, 'load_source', return_value=(observed, candidates, source_data, source_manifest, clock)):
                report = module.build(source, output, spec, {'folds': []})
                self.assertEqual(report['model_fits'], 0)
                replay, _, _ = module.load_bundle(output, source, spec, {'folds': []}, ledger)
                np.testing.assert_array_equal(replay['data'].X, data.X)
                self.assertEqual(ledger.path.read_bytes(), before)
                with self.assertRaises(FileExistsError):
                    module.build(source, output, spec, {'folds': []})
                (output/'opportunities.npz').write_bytes(b'changed')
                with self.assertRaisesRegex(ValueError, 'artifact changed'):
                    module.load_bundle(output, source, spec, {'folds': []}, ledger)
