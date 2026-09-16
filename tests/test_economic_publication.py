"""Publication-only correction: exact amounts, durability and frozen executable."""
import copy
from fractions import Fraction
import io
import json
from pathlib import Path
import tempfile
from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import Mock, patch

from scripts import publish_economic_portfolios as publisher
from fxnn.economic_lifecycle import fingerprint, atomic_json
from fxnn.economic_report import build_report, markdown, aggregate_csv
from test_economic_report import fixture


def native_fixture(confirmation=False):
    def native(value):
        if isinstance(value, dict):
            if set(value) == {'numerator', 'denominator'}:
                return Fraction(value['numerator'], value['denominator'])
            return {key: native(item) for key, item in value.items()}
        if isinstance(value, list):
            return [native(item) for item in value]
        return value
    result = native(fixture(confirmation))
    # A nonterminating decimal must never be converted through float or Decimal.
    result['scenarios'][0]['total']['commission'] = Fraction(1, 3)
    return result


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.target = self.root / 'aggregate-development.json'
        self.life = Mock()
        self.decoded, self.encoded = publisher.exact_json(native_fixture(), False)

    def test_exact_fraction_null_and_both_complete_report_modes(self):
        dev, conf = native_fixture(), native_fixture(True)
        dd, _ = publisher.exact_json(dev, False)
        cc, _ = publisher.exact_json(conf, True)
        self.assertEqual(dd['scenarios'][0]['total']['commission'], {'numerator': 1, 'denominator': 3})
        for kwargs, decoded_kwargs in [({}, {}),
            ({'confirmation': {'execution_status': 'COMPLETED', 'portfolios': conf}},
             {'confirmation': {'execution_status': 'COMPLETED', 'portfolios': cc}})]:
            raw = build_report(None, None, dev, **kwargs)
            decoded = build_report(None, None, dd, **decoded_kwargs)
            self.assertEqual(raw, decoded)
            self.assertEqual(markdown(raw), markdown(decoded))
            self.assertEqual(aggregate_csv(raw), aggregate_csv(decoded))

    def test_codec_rejects_key_coercion_and_nonfinite_numbers(self):
        for extra in ({1: 'integer', '1': 'string'}, float('nan')):
            result = native_fixture(); result['extra'] = extra
            with self.assertRaises(ValueError):
                publisher.exact_json(result, False)

    def test_failed_pending_preserved_before_publish_and_same_byte_retry(self):
        pending = self.target.with_suffix('.pending'); pending.write_bytes(b'{"partial":')
        first = publisher.publish_aggregate(self.target, self.decoded, self.encoded, self.life)
        preserved = list(self.root.glob('aggregate-development.pending.partial-*'))
        self.assertEqual(len(preserved), 1)
        self.assertEqual(preserved[0].read_bytes(), b'{"partial":')
        self.assertFalse(pending.exists())
        self.assertEqual(self.target.read_text(), self.encoded)
        before = self.target.stat().st_mtime_ns
        second = publisher.publish_aggregate(self.target, self.decoded, self.encoded, self.life)
        self.assertEqual(first, second)
        self.assertEqual(before, self.target.stat().st_mtime_ns)
        self.life.poison.assert_not_called()

    def test_conflicting_destination_untouched_and_poisoned(self):
        self.target.write_text('conflict')
        with self.assertRaisesRegex(ValueError, 'differs'):
            publisher.publish_aggregate(self.target, self.decoded, self.encoded, self.life)
        self.assertEqual(self.target.read_text(), 'conflict')
        self.life.poison.assert_called_once()

    def test_concurrent_publishers_preserve_single_partial_and_identical_result(self):
        self.target.with_suffix('.pending').write_text('partial')
        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(lambda _: publisher.publish_aggregate(
                self.target, self.decoded, self.encoded, self.life), range(3)))
        self.assertEqual(results, [results[0]] * 3)
        self.assertEqual(len(list(self.root.glob('*.partial-*'))), 1)
        self.life.poison.assert_not_called()

    def test_interruption_before_each_forensic_sync_is_finished_before_retry_write(self):
        for interrupted_call in (1, 2):
            with self.subTest(sync_call=interrupted_call):
                folder = self.root / str(interrupted_call); folder.mkdir()
                target = folder / self.target.name
                target.with_suffix('.pending').write_text('forensic')
                original_sync = publisher.sync
                calls = 0
                def interrupted(path):
                    nonlocal calls
                    calls += 1
                    if calls == interrupted_call:
                        raise KeyboardInterrupt()
                    original_sync(path)
                with patch.object(publisher, 'sync', side_effect=interrupted):
                    with self.assertRaises(KeyboardInterrupt):
                        publisher.publish_aggregate(target, self.decoded, self.encoded, self.life)
                preserved = list(folder.glob('*.partial-*'))
                self.assertEqual([p.read_text() for p in preserved], ['forensic'])
                self.assertFalse(target.exists())
                events = []
                original_atomic = publisher.atomic_json
                def synced(path):
                    events.append(('sync', path)); original_sync(path)
                def published(path, value):
                    events.append(('write', path)); original_atomic(path, value)
                with patch.object(publisher, 'sync', side_effect=synced), patch.object(publisher, 'atomic_json', side_effect=published):
                    publisher.publish_aggregate(target, self.decoded, self.encoded, self.life)
                self.assertEqual(events[:3], [('sync', preserved[0]), ('sync', folder), ('write', target)])
        self.life.poison.assert_not_called()

    def test_interruption_between_destination_rename_and_parent_sync(self):
        from fxnn import economic_lifecycle
        original_replace = economic_lifecycle.os.replace
        def interrupted(source, destination):
            original_replace(source, destination)
            raise SystemExit('after rename, before parent fsync')
        with patch.object(economic_lifecycle.os, 'replace', side_effect=interrupted):
            with self.assertRaises(SystemExit):
                publisher.publish_aggregate(self.target, self.decoded, self.encoded, self.life)
        with patch.object(publisher, 'sync', wraps=publisher.sync) as sync:
            publisher.publish_aggregate(self.target, self.decoded, self.encoded, self.life)
        self.assertEqual([call.args[0] for call in sync.call_args_list], [self.target, self.root])
        self.life.poison.assert_not_called()

    def test_existing_aggregate_retry_also_finishes_preserved_file_sync(self):
        self.target.write_text(self.encoded)
        preserved = self.root / 'aggregate-development.pending.partial-synthetic'
        preserved.write_text('preserved')
        with patch.object(publisher, 'sync', wraps=publisher.sync) as sync:
            publisher.publish_aggregate(self.target, self.decoded, self.encoded, self.life)
        self.assertEqual([c.args[0] for c in sync.call_args_list], [preserved, self.root, self.target, self.root])

    def test_lock_open_and_flock_storage_errors_poison_without_data_mutation(self):
        original_open = Path.open
        pending = self.target.with_suffix('.pending'); pending.write_text('original')
        for point in ('open', 'flock'):
            self.life.reset_mock()
            def failed_open(path, *args, **kwargs):
                if path.name.endswith('.publication.lock'):
                    raise OSError('lock open')
                return original_open(path, *args, **kwargs)
            manager = patch.object(Path, 'open', new=failed_open) if point == 'open' else patch.object(publisher.fcntl, 'flock', side_effect=OSError('flock'))
            with manager:
                with self.assertRaises(OSError):
                    publisher.publish_aggregate(self.target, self.decoded, self.encoded, self.life)
            self.assertFalse(self.target.exists())
            self.assertEqual(pending.read_text(), 'original')
            self.assertEqual(list(self.root.glob('*.partial-*')), [])
            self.life.poison.assert_called_once()

    def test_lock_setup_process_interruption_does_not_poison(self):
        with patch.object(publisher.fcntl, 'flock', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                publisher.publish_aggregate(self.target, self.decoded, self.encoded, self.life)
        self.assertFalse(self.target.exists())
        self.life.poison.assert_not_called()

    def test_observed_storage_failure_poisons_without_publishing(self):
        with patch.object(publisher, 'atomic_json', side_effect=OSError('disk')):
            with self.assertRaises(OSError):
                publisher.publish_aggregate(self.target, self.decoded, self.encoded, self.life)
        self.assertFalse(self.target.exists())
        self.life.poison.assert_called_once()

    def test_same_byte_sync_failure_is_not_success(self):
        self.target.write_text(self.encoded)
        with patch.object(publisher, 'sync', side_effect=OSError('fsync')):
            with self.assertRaises(OSError):
                publisher.publish_aggregate(self.target, self.decoded, self.encoded, self.life)
        self.life.poison.assert_called_once()


class FrozenPublisherTests(unittest.TestCase):
    def setup_package(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        root = Path(temp.name).resolve(); helper = root / publisher.RELATIVE_PATH
        helper.parent.mkdir(); helper.write_bytes(b'committed helper\n')
        receipt = root / 'validation.json'
        value = {'head_sha': 'a' * 40, 'publication_adapter': {
            'repository_relative_path': publisher.RELATIVE_PATH, 'artifact': fingerprint(helper)}}
        atomic_json(receipt, value)
        R = {'sha': 'a' * 40, 'reports': {'receipt_validation': fingerprint(receipt)}}
        package = {'S': 'b' * 64, 'R': R}; freeze = root / 'freeze.json'
        atomic_json(freeze, package)
        snapshot = {'sealed': True, 'S': package['S'], 'R': R, 'P': fingerprint(freeze)}
        return root, helper, receipt, value, freeze, snapshot

    def rebind(self, receipt, value, freeze, snapshot):
        atomic_json(receipt, value)
        snapshot['R']['reports']['receipt_validation'] = fingerprint(receipt)
        atomic_json(freeze, {'S': snapshot['S'], 'R': snapshot['R']})
        snapshot['P'] = fingerprint(freeze)

    def test_exact_helper_receipt_freeze_and_original_release_git_blob(self):
        root, helper, _, _, _, snapshot = self.setup_package()
        with patch.object(publisher.subprocess, 'check_output', return_value=helper.read_bytes()) as git:
            self.assertEqual(publisher.verify_frozen_publisher(root, snapshot), fingerprint(helper))
        self.assertIn('a' * 40 + ':' + publisher.RELATIVE_PATH, git.call_args.args[0])

    def test_missing_noncanonical_binding_and_wrong_release_are_rejected(self):
        for mutation in ('missing', 'relative', 'absolute', 'sha'):
            with self.subTest(mutation=mutation):
                root, helper, receipt, value, freeze, snapshot = self.setup_package()
                if mutation == 'missing': value.pop('publication_adapter')
                elif mutation == 'relative': value['publication_adapter']['repository_relative_path'] = 'alias.py'
                elif mutation == 'absolute': value['publication_adapter']['artifact']['path'] = str(root / 'alias.py')
                else: value['head_sha'] = 'c' * 40
                self.rebind(receipt, value, freeze, snapshot)
                with patch.object(publisher.subprocess, 'check_output', return_value=helper.read_bytes()):
                    with self.assertRaises(ValueError): publisher.verify_frozen_publisher(root, snapshot)

    def test_modified_helper_receipt_freeze_or_git_blob_rejected(self):
        for mutation in ('helper', 'receipt', 'freeze', 'git', 'R', 'S'):
            with self.subTest(mutation=mutation):
                root, helper, receipt, _, freeze, snapshot = self.setup_package()
                committed = helper.read_bytes()
                if mutation == 'helper': helper.write_bytes(b'changed helper')
                elif mutation == 'receipt': receipt.write_text('{}')
                elif mutation == 'freeze': freeze.write_text('{}')
                elif mutation == 'R': snapshot['R'] = {'sha': 'd' * 40}
                elif mutation == 'S': snapshot['S'] = 'd' * 64
                else: committed = b'another Git blob'
                with patch.object(publisher.subprocess, 'check_output', return_value=committed):
                    with self.assertRaises(ValueError): publisher.verify_frozen_publisher(root, snapshot)


if __name__ == '__main__':
    unittest.main()
