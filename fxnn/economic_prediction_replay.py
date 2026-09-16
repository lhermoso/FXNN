"""Read-only exact replay of stage9 probability artifacts and operational rows."""
import json
import math
from pathlib import Path

import numpy as np

from fxnn.economic_clock import utc_ms
from fxnn.economic_fit import phase_plan, phase_predictions, runtime, verified_model, verify_phases
from fxnn.economic_lifecycle import verify_manifest
from fxnn.mlp_comparison import array_hash

EXPERIMENT = 'economic_ticks_v1'
FAMILIES = ('constant', 'logistic')


def _read(artifact):
    verify_manifest({'artifact': artifact})
    with Path(artifact['path']).open(encoding='utf8') as stream:
        result = json.load(stream)
    verify_manifest({'artifact': artifact})
    return result


def _checkpoint(snapshot, phase, artifact):
    checkpoints = [c for c in snapshot['checkpoints'] if c.get('phase') == phase]
    if len(checkpoints) != 1 or checkpoints[0]['artifacts'].get('report') != artifact:
        raise ValueError('Model report lacks its unique authoritative checkpoint')


def authenticate_frozen_models(config, supervisor, final_report_artifact, *, replay=False):
    """Authenticate P/S/R, checkpoint, final source contracts and model terminals."""
    snapshot = supervisor.read()
    verify_manifest(snapshot['files'])
    if snapshot['config'] != config or runtime() != config['versions']:
        raise ValueError('Frozen scientific config/runtime changed')
    if not replay and (snapshot.get('poison') or snapshot.get('terminal')):
        raise ValueError('Terminal or poisoned confirmation cannot generate predictions')
    allowed = ('OPENED', 'COMPLETED', 'INCOMPLETE') if replay else ('OPENED',)
    if not snapshot['sealed'] or snapshot['guard'] not in allowed:
        raise ValueError('Recorded confirmation access required; generation is OPENED-only')
    package = _read(snapshot['P'])
    if (package['S'] != snapshot['S'] or package['R'] != snapshot['R'] or
            package['fits'] != snapshot['fits'] or package['guard'] != 'UNOPENED'):
        raise ValueError('Frozen P/S/R or fit provenance mismatch')
    if package['technical_tests'] != dict.fromkeys(('T1','T2','T3','T4','T5'), True):
        raise ValueError('Frozen technical prerequisites mismatch')
    verify_manifest(package['R']['reports'])
    if final_report_artifact not in package['R']['reports'].values():
        raise ValueError('Final model report is not bound in the frozen release')
    _checkpoint(snapshot, 'FINAL_MODELS_VERIFIED', final_report_artifact)
    final = _read(final_report_artifact)
    if (final['segment'] != 'final' or final['S'] != snapshot['S'] or
            len(final['phases']) != 1 or final['phases'][0]['phase']['name'] != 'final' or
            set(final['phases'][0]['families']) != set(FAMILIES)):
        raise ValueError('Final model report identity/coverage mismatch')
    frozen = package['models']
    if len(frozen) != 2 or {m['contract']['family'] for m in frozen} != set(FAMILIES):
        raise ValueError('Exactly two distinct frozen model families required')
    result = {}
    for family in FAMILIES:
        member = next(m for m in frozen if m['contract']['family'] == family)
        saved = final['phases'][0]['families'][family]['fit']
        matches = [m for m in snapshot['fits'].values() if m['F'] == member['F']]
        if len(matches) != 1 or matches[0] != member or member['status'] != 'succeeded':
            raise ValueError('Frozen model no longer matches authoritative fit')
        if saved['contract'] != member['contract']:
            raise ValueError('Final model source contract differs from P')
        state, fitted = verified_model(supervisor, member['contract'])
        if state is None or fitted != saved:
            raise ValueError('Frozen final model report/terminal mismatch')
        result[family] = (state, fitted)
    return snapshot, result


def authenticate_confirmation_matrix(supervisor, snapshot, matrix, evidence_artifact):
    """Verify confirmation manifests and their S/P binding, never market payloads.

    Caller loads matrix via load_window_data from these authenticated artifacts.
    Provenance validation here prevents substitution of development/other-window
    matrices but does not replace that loader's numeric input hash checks.
    """
    evidence = _read(evidence_artifact)
    if (evidence['S'] != snapshot['S'] or evidence['freeze_sha256'] != snapshot['P']['sha256'] or
            evidence['confirmation_access'] is not True or evidence['scientific_fits'] != 0):
        raise ValueError('Confirmation source evidence differs from frozen S/P')
    canonical = supervisor.root/'confirmation-source-v1'/'manifest.json'
    if Path(evidence['source_manifest']['path']).resolve() != canonical.resolve():
        raise ValueError('Confirmation source receipt is outside canonical acquisition')
    verify_manifest({k: evidence[k] for k in ('dataset', 'labels', 'source_manifest')})
    dataset = _read(evidence['dataset'])
    labels = _read(evidence['labels'])
    contract = dataset['contract']
    expected = {'experiment': EXPERIMENT, 'phase': 'confirmation', 'S': snapshot['S'],
                'freeze_sha256': snapshot['P']['sha256'],
                'source_manifest_sha256': evidence['source_manifest']['sha256']}
    if any(contract.get(key) != value for key, value in expected.items()):
        raise ValueError('Confirmation dataset contract does not bind S/P/source')
    if labels['dataset_manifest_sha256'] != evidence['dataset']['sha256']:
        raise ValueError('Confirmation label source mismatch')
    root = Path(evidence['dataset']['path']).parent
    index_artifact = dict(dataset['files']['index/manifest.json'], path=str((root/'index/manifest.json').resolve()))
    index = _read(index_artifact)
    expected_provenance = {'dataset_manifest': evidence['dataset']['sha256'],
                          'labels_manifest': evidence['labels']['sha256'],
                          'index_manifest': index_artifact['sha256'],
                          'hazard_sha256': index['files']['hazards.json']['sha256']}
    if matrix.provenance != expected_provenance or len(matrix) != dataset['expected_opportunities']:
        raise ValueError('Matrix is not the authenticated confirmation dataset')
    first, stop = utc_ms('2024-01-01T00:00:00+00:00'), utc_ms('2025-01-01T00:00:00+00:00')
    if np.any((matrix.decision_ms < first) | (matrix.decision_ms >= stop)):
        raise ValueError('Confirmation matrix contains another window')
    return evidence


def compare_arrays(artifact, expected):
    verify_manifest({'predictions': artifact})
    with np.load(artifact['path'], allow_pickle=False) as archive:
        if set(archive.files) != set(expected):
            raise ValueError('Prediction archive schema mismatch')
        for key, value in expected.items():
            saved = archive[key]
            if saved.dtype != value.dtype or saved.shape != value.shape or array_hash(saved) != array_hash(value):
                raise ValueError('Prediction array dtype/shape/content mismatch: '+key)
            if not np.array_equal(saved, value, equal_nan=True):
                raise ValueError('Prediction array replay mismatch: '+key)
    verify_manifest({'predictions': artifact})


def operational_rows(arrays, model_available):
    """Complete validated rows. Never zip silently unequal vectors."""
    times, probabilities = arrays['decision_ms'], arrays['probability']
    if (times.ndim != 1 or probabilities.ndim != 1 or times.shape != probabilities.shape or
            not np.issubdtype(times.dtype, np.integer) or type(model_available) is not bool):
        raise ValueError('Aligned integer decision/probability vectors required')
    if np.any(np.diff(times) <= 0) or np.any(np.isinf(probabilities)):
        raise ValueError('Ordered unique decisions and finite-or-NaN probabilities required')
    available = np.isfinite(probabilities)
    if np.any((probabilities[available] < 0) | (probabilities[available] > 1)) or not model_available and available.any():
        raise ValueError('Operational probability contradicts model availability')
    for i in range(len(times)):
        time = int(times[i])
        yield {'id': f'{EXPERIMENT}:{time}', 'decision_ms': time,
               'probability': float(probabilities[i]) if available[i] else None,
               'model_available': model_available}


def compare_operational(artifact, expected_rows):
    verify_manifest({'operational': artifact})
    count, previous = 0, None
    with Path(artifact['path']).open(encoding='utf8') as stream:
        for expected in expected_rows:
            line = stream.readline()
            if not line:
                raise ValueError('Operational prediction row missing')
            actual = json.loads(line, parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Nonfinite JSON number')))
            if (not isinstance(actual, dict) or set(actual) != set(expected) or
                    type(actual.get('decision_ms')) is not int or type(actual.get('model_available')) is not bool):
                raise ValueError('Operational row schema/type mismatch')
            probability = actual['probability']
            if probability is not None and (type(probability) not in (float,int) or not math.isfinite(probability) or not 0 <= probability <= 1):
                raise ValueError('Invalid operational probability')
            if actual != expected or previous is not None and actual['decision_ms'] <= previous:
                raise ValueError('Operational prediction replay mismatch')
            previous = actual['decision_ms']
            count += 1
        if stream.readline():
            raise ValueError('Unexpected extra operational prediction row')
    verify_manifest({'operational': artifact})
    return count


def verify_final_probabilities(config, supervisor, matrix, final_report_artifact,
                               predictions_report_artifact, confirmation_evidence_artifact):
    snapshot, models = authenticate_frozen_models(config, supervisor, final_report_artifact, replay=True)
    authenticate_confirmation_matrix(supervisor, snapshot, matrix, confirmation_evidence_artifact)
    report = _read(predictions_report_artifact)
    phase = {'name': 'confirmation', 'evaluation_start_ms': utc_ms('2024-01-01T00:00:00+00:00'),
             'evaluation_end_ms': utc_ms('2025-01-01T00:00:00+00:00')}
    if (report['phase'] != phase or report['scientific_fits'] != 0 or set(report['families']) != set(FAMILIES) or
            report['S'] != snapshot['S'] or report['freeze_sha256'] != snapshot['P']['sha256'] or
            report['confirmation_evidence_sha256'] != confirmation_evidence_artifact['sha256']):
        raise ValueError('Confirmation prediction report identity mismatch')
    count = 0
    for family in FAMILIES:
        state, fitted = models[family]
        saved = report['families'][family]
        arrays, metrics = phase_predictions(matrix, state, phase)
        if saved['fit'] != fitted or saved['metrics'] != metrics:
            raise ValueError('Confirmation model/metrics replay mismatch')
        compare_arrays(saved['predictions'], arrays)
        if family == 'logistic':
            count = compare_operational(report['operational'], operational_rows(arrays, True))
    return {'rows': count, 'scientific_fits': 0, 'ledger_writes': 0, 'guard': snapshot['guard']}


def verify_operational_predictions(config, supervisor, matrix, clock, model_report_artifact, operational_artifact):
    snapshot = supervisor.read()
    if snapshot['config'] != config or runtime() != config['versions']:
        raise ValueError('Registered development config/runtime changed')
    _checkpoint(snapshot, 'DEVELOPMENT_VERIFIED', model_report_artifact)
    report = verify_phases(matrix, clock, phase_plan(config['folds']), config['logistic'],
                           config['versions'], supervisor, model_report_artifact)
    def rows():
        for phase in report['phases']:
            if phase['phase']['name'].endswith(':refit'):
                family = phase['families']['logistic']
                with np.load(family['predictions']['path'], allow_pickle=False) as arrays:
                    yield from operational_rows(arrays, family['fit']['status'] == 'succeeded')
    count = compare_operational(operational_artifact, rows())
    return {'rows': count, 'scientific_fits': 0, 'ledger_writes': 0}
