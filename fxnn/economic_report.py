"""Exact aggregate stage9 decisions and compact Portuguese research reports.

No source loading, fits, lifecycle transitions or confirmation waivers. Input
portfolios are already verified aggregate reports, never transactions or prices.
"""
import csv
from decimal import Decimal, localcontext
from fractions import Fraction
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re

from fxnn.economic_account import economic_diagnostics

POLICIES = ('P0', 'P1')
BUNDLES = ('S0', 'S1', 'S2')
ARMS = ('primary', 'filtered')
DEVELOPMENT_QUARTERS = ('2023Q2', '2023Q3', '2023Q4')
CONFIRMATION_QUARTERS = ('2024Q1', '2024Q2', '2024Q3', '2024Q4')
EXECUTION = {'UNOPENED': '2024 não realizado; reserva não aberta',
             'OPENING': 'abertura de 2024 consumida; recebimento ainda não confirmado',
             'OPENED': '2024 aberto; avaliação ainda não concluída',
             'COMPLETED': 'avaliação de 2024 concluída',
             'INCOMPLETE': 'avaliação de 2024 encerrada incompleta'}
AMOUNTS = ('conclusive_equity', 'conclusive_pnl', 'scenario_equity', 'scenario_pnl', 'cash',
           'known_cash', 'realized_pnl', 'conclusive_unrealized', 'scenario_unrealized', 'net_return',
           'commission', 'slippage_attribution_only', 'funding_recorded', 'funding_if_still_open',
           'turnover_eur', 'turnover_usd', 'peak_notional', 'last_known_equity', 'max_dollar_drawdown',
           'drawdown_fraction_initial', 'realized_recorded', 'recorded_cashflow', 'conditional_funding')
COUNTS = ('wall_exposure_ms', 'open_exposure_ms', 'mark_count', 'mark_missing', 'opportunities', 'entries', 'exits')
BOOLEANS = ('arm_model_available', 'model_available', 'potential_exposure_unknown', 'capital_breach',
            'conditional_scenario_not_lower_bound', 'profit_claim')


def tri_all(values):
    values = list(values)
    if not values or any(value is not None and type(value) is not bool for value in values):
        raise ValueError('Nonempty explicit three-valued criteria required')
    if False in values:
        return False
    return None if None in values else True


def _exact(value):
    if value is None:
        return None
    if isinstance(value, Fraction):
        return value
    if type(value) is int:
        return Fraction(value)
    if isinstance(value, dict) and set(value) == {'numerator', 'denominator'}:
        if type(value['numerator']) is not int or type(value['denominator']) is not int or value['denominator'] <= 0:
            raise ValueError('Exact rational aggregate required')
        return Fraction(value['numerator'], value['denominator'])
    if isinstance(value, (str, Decimal)):
        number = Decimal(value)
        if number.is_finite():
            return Fraction(number)
    raise ValueError('Financial aggregates require exact finite amounts, never binary floats')


def _json_amount(value):
    number = _exact(value)
    return None if number is None else {'numerator': number.numerator, 'denominator': number.denominator}


def _count(value):
    if type(value) is not int or value < 0:
        raise ValueError('Nonnegative aggregate count required')
    return value


def _counters(value):
    if not isinstance(value, dict) or len(value) > 256:
        raise ValueError('Bounded aggregate counter dictionary required')
    result = {}
    for key, number in value.items():
        if not isinstance(key, str) or re.fullmatch('[a-z][a-z0-9_]{0,63}', key) is None:
            raise ValueError('Counter names must be aggregate identifiers')
        result[key] = _count(number)
    return result


def _aggregate(record, *, quarter=False):
    """Allowlist numeric aggregate fields; do not carry paths/quotes/journals."""
    required = {'conclusive_pnl', 'max_dollar_drawdown', 'capital_breach', 'blocked'}
    required |= {'model_available', 'opportunities'} if quarter else {'arm_model_available', 'counts', 'state'}
    if not required <= set(record):
        raise ValueError('Required portfolio aggregate fields missing')
    result = {key: _json_amount(record[key]) for key in AMOUNTS if key in record}
    result.update({key: _count(record[key]) for key in COUNTS if key in record})
    for key in BOOLEANS:
        if key in record:
            if type(record[key]) is not bool:
                raise ValueError('Explicit boolean aggregate required')
            result[key] = record[key]
    result['blocked'] = _counters(record['blocked'])
    if not quarter:
        result['counts'] = _counters(record['counts'])
        if 'opportunities' not in result['counts']:
            raise ValueError('Full opportunity denominator required')
        state = record['state']
        if state not in ('FLAT', 'PENDING_ENTRY', 'PENDING_TIMEOUT_EXIT', 'OPEN', 'UNRESOLVED', 'ENDED'):
            raise ValueError('Unknown portfolio state')
        result['state'] = state
    return result


def collect_portfolios(accounts, periods):
    """Capture reports from the Simulator's12 accounts; period tuples name boundaries.

    periods=[('2023Q2','initial','2023Q3'), ...]. Account.quarterly requires
    adjacent actual snapshot names. The caller owns the calendar and completion.
    """
    expected = {(p, b, a) for p in POLICIES for b in BUNDLES for a in ARMS}
    if set(accounts) != expected:
        raise ValueError('All12 predeclared portfolio accounts required')
    names = [period[0] for period in periods]
    if len(names) != len(set(names)):
        raise ValueError('Unique quarter identities required')
    scenarios = []
    for policy in POLICIES:
        for bundle in BUNDLES:
            for arm in ARMS:
                account = accounts[policy, bundle, arm]
                scenarios.append({'policy': policy, 'bundle': bundle, 'arm': arm,
                                  'total': account.report(),
                                  'quarters': {name: account.quarterly(left, right) for name, left, right in periods}})
    return {'scenarios': scenarios,
            'account_diagnostics': economic_diagnostics(accounts, [(left, right) for _, left, right in periods])}


def _positive(value):
    return None if value is None else value > 0


def _criteria(primary, filtered):
    p = _exact(primary['conclusive_pnl'])
    f = _exact(filtered['conclusive_pnl'])
    filtered_available = filtered.get('model_available', filtered.get('arm_model_available'))
    available = primary.get('model_available', primary.get('arm_model_available')) and filtered_available
    return {'filtered_positive': _positive(f) if filtered_available else None,
            'filtered_improves_primary': None if not available or p is None or f is None else f > p}


def evaluate_portfolios(portfolios, *, confirmation=False):
    required_quarters = CONFIRMATION_QUARTERS if confirmation else DEVELOPMENT_QUARTERS
    scenarios = portfolios['scenarios']
    by_identity = {}
    for record in scenarios:
        key = (record['policy'], record['bundle'], record['arm'])
        if key in by_identity or key[0] not in POLICIES or key[1] not in BUNDLES or key[2] not in ARMS:
            raise ValueError('Duplicate or unregistered scenario')
        if set(record['quarters']) != set(required_quarters):
            raise ValueError('Every registered quarter must remain present')
        by_identity[key] = {'policy': key[0], 'bundle': key[1], 'arm': key[2],
                            'total': _aggregate(record['total']),
                            'quarters': {q: _aggregate(record['quarters'][q], quarter=True) for q in required_quarters}}
    expected = {(p, b, a) for p in POLICIES for b in BUNDLES for a in ARMS}
    if set(by_identity) != expected:
        raise ValueError('All12 predeclared scenarios required; no dropped arm/window')
    # Every account receives the same scheduled grid, including absorbing states.
    totals = {record['total']['counts']['opportunities'] for record in by_identity.values()}
    if len(totals) != 1:
        raise ValueError('Scenario opportunity denominators differ')
    for q in required_quarters:
        if len({record['quarters'][q]['opportunities'] for record in by_identity.values()}) != 1:
            raise ValueError('Quarter opportunity denominators differ')
    for record in by_identity.values():
        if sum(record['quarters'][q]['opportunities'] for q in required_quarters) != record['total']['counts']['opportunities']:
            raise ValueError('Quarter opportunity denominators do not cover total')
    policy_results = {}
    for policy in POLICIES:
        primary = by_identity[policy, 'S1', 'primary']
        filtered = by_identity[policy, 'S1', 'filtered']
        quarter_components = {q: _criteria(primary['quarters'][q], filtered['quarters'][q]) for q in required_quarters}
        g4 = tri_all(v for item in quarter_components.values() for v in item.values())
        stress = by_identity[policy, 'S2', 'filtered']['total']
        available = stress['arm_model_available']
        pnl, dd = _exact(stress['conclusive_pnl']), _exact(stress['max_dollar_drawdown'])
        stress_components = {'positive_pnl': _positive(pnl) if available else None,
                             'drawdown_at_most_500_usd': None if not available or dd is None else dd <= 500,
                             'no_capital_breach': not stress['capital_breach']}
        g5 = tri_all(stress_components.values())
        annual = _criteria(primary['total'], filtered['total'])
        combined = tri_all([g4, g5]+(list(annual.values()) if confirmation else []))
        policy_results[policy] = {'quarterly_s1': quarter_components, 'G4': g4,
                                  'stress_s2': stress_components, 'G5': g5,
                                  'annual_s1': annual, 'promotion': combined,
                                  'main_evidence': policy == 'P0', 'counterfactual_not_lower_bound': policy == 'P1'}
    promotion = policy_results['P0']['promotion']
    return {'status': 'PROMOTED' if promotion is True else 'REJECTED' if promotion is False else 'INCONCLUSIVE',
            'promotion': promotion, 'policies': policy_results,
            'quarters': list(required_quarters),
            'scenarios': [by_identity[p,b,a] for p in POLICIES for b in BUNDLES for a in ARMS],
            'opportunity_denominator': next(iter(totals)), 'minimum_trade_floor': None,
            'material_uncertainty': any(
                v['conclusive_pnl'] is None or v['max_dollar_drawdown'] is None or
                not v.get('model_available', v.get('arm_model_available', True))
                for record in by_identity.values() for v in [record['total'], *record['quarters'].values()]),
            'opening_gate': False}


def _finite_tree(value):
    """Small numeric metric/support trees only; no arbitrary arrays or strings."""
    if value is None or type(value) in (int, bool):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    if isinstance(value, dict):
        if len(value) > 64:
            raise ValueError('Metric tree too broad')
        return {str(k): _finite_tree(v) for k, v in value.items()}
    if isinstance(value, list) and len(value) <= 10:
        return [_finite_tree(item) for item in value]
    raise ValueError('Only finite compact metric values are publishable')


def model_summary(report, *, final=False):
    if report is None:
        return {'provided': False, 'phases': [], 'economic_evidence': False}
    result = []
    for record in report['phases']:
        name = record['phase']['name']
        if not isinstance(name, str) or re.fullmatch('[A-Za-z0-9:_-]{1,48}', name) is None:
            raise ValueError('Safe phase identifier required')
        models = {}
        if set(record['families']) != {'constant', 'logistic'}:
            raise ValueError('Both registered model families required')
        for family in ('constant', 'logistic'):
            item = record['families'][family]
            trained = item['fit']
            if trained['status'] not in ('succeeded', 'failed', 'technically_unavailable'):
                raise ValueError('Terminal/technical model status required')
            entry = {'fit_status': trained['status'], 'training_support': _finite_tree(trained['support'])}
            reason = trained.get('reason')
            if reason in ('empty_training', 'logistic_requires_two_classes'):
                entry['unavailable_reason'] = reason
            if not final and 'metrics' in item:
                metrics = item['metrics']
                entry.update({k: _count(metrics[k]) for k in ('rows', 'available_probabilities', 'metric_rows', 'proxy_unobserved_by_boundary')})
                entry['absence_counts'] = _counters(metrics['absence_counts'])
                scored = metrics['score']
                allowed = ('log_loss', 'brier', 'average_precision', 'roc_auc', 'support',
                           'fixed_half_confusion', 'reliability_deciles')
                entry['TP_proxy_diagnostics'] = {k: _finite_tree(scored[k]) for k in allowed if k in scored}
            models[family] = entry
        result.append({'phase': name, 'models': models})
    return {'provided': True, 'phases': result, 'economic_evidence': False,
            'target': 'proxy TP-primeiro S0; classificação não mede lucro operacional'}


def _artifact_table(artifacts):
    rows = []
    for name, value in sorted(artifacts.items()):
        if re.fullmatch('[A-Za-z0-9_. -]{1,80}', name) is None:
            raise ValueError('Safe aggregate artifact label required')
        sha = value['sha256']
        if not isinstance(sha, str) or re.fullmatch('[0-9a-f]{64}', sha) is None:
            raise ValueError('SHA256 aggregate artifact binding required')
        rows.append({'artifact': name, 'bytes': _count(value['bytes']), 'sha256': sha})
    return rows


def build_report(model_development, model_final, development, *, confirmation=None, artifacts=None):
    dev = evaluate_portfolios(development)
    confirmation = {'execution_status': 'UNOPENED'} if confirmation is None else confirmation
    execution = confirmation['execution_status']
    if execution not in EXECUTION:
        raise ValueError('Explicit monotonic confirmation execution status required')
    supplied = confirmation.get('portfolios')
    if execution == 'UNOPENED' and supplied is not None:
        raise ValueError('Unopened confirmation cannot contain evaluated portfolios')
    if execution == 'COMPLETED' and supplied is None:
        raise ValueError('Completed confirmation requires all scenario/window aggregates')
    confirmed = None if supplied is None else evaluate_portfolios(supplied, confirmation=True)
    # Incomplete/pending positive aggregates cannot constitute confirmation.
    # A fully determinate registered economic failure remains a rejection.
    economic = None if confirmed is None else confirmed['promotion']
    effective = economic if economic is False or execution == 'COMPLETED' else None
    decision = tri_all([dev['promotion'], effective])
    code = 'PAPER_TRADING_PLANNING_CONDITIONAL' if decision is True else 'REJECT_PROMOTION' if decision is False else 'EXPLORATION_ONLY'
    return {'experiment': 'economic_ticks_v1', 'development': dev,
            'confirmation': {'execution_status': execution, 'execution_description_pt': EXECUTION[execution],
                             'economic_result': confirmed, 'promotion': effective,
                             'completed_with_uncertainty': execution == 'COMPLETED' and confirmed['material_uncertainty']},
            'combined_decision': code,
            'models': {'development': model_summary(model_development), 'final_pre2024': model_summary(model_final, final=True)},
            'artifact_hashes': _artifact_table(artifacts or {}),
            'opening_authorization': False, 'technical_T1_T5_owned_by_supervisor': True,
            'profit_claim': False,
            'limitations_pt': ['Custos e funding são hipóteses congeladas, não tarifas históricas comprovadas.',
                'P1 é um cenário contrafactual, não um limite inferior, e não resgata P0.',
                'Probabilidade ausente não equivale a rejeição do filtro; comparação indisponível não equivale a zero.',
                'PnL usa patrimônio marcado nos limites dos trimestres; PnL e drawdown inconclusivos permanecem nulos.',
                'Funding condicional de P0 permanece separado do caixa conhecido.',
                'Uma promoção permite apenas planejar paper trading condicionado à validação posterior dos termos da corretora.',
                'Resultados econômicos não autorizam omitir a confirmação quando T1–T5 forem satisfeitos.']}


def _display(value):
    if value is None:
        return 'indisponível'
    number = _exact(value)
    with localcontext() as context:
        context.prec = 40
        return format(Decimal(number.numerator)/Decimal(number.denominator), '.2f')


def _status(value):
    return 'passou' if value is True else 'falhou' if value is False else 'inconclusivo'


def markdown(report):
    labels = {'PAPER_TRADING_PLANNING_CONDITIONAL': 'Planejamento condicional de paper trading',
              'REJECT_PROMOTION': 'Promoção rejeitada para esta configuração',
              'EXPLORATION_ONLY': 'Manter somente exploração'}
    lines = ['# Pesquisa econômica FXNN — etapa9', '', '## Decisão', '',
             labels[report['combined_decision']]+'.', '',
             'Desenvolvimento: '+_status(report['development']['promotion'])+'.',
             'Confirmação: '+report['confirmation']['execution_description_pt']+'.',
             'Resultado econômico da confirmação: '+_status(report['confirmation']['promotion'])+'.', '']
    if report['confirmation']['completed_with_uncertainty']:
        lines += ['A avaliação foi concluída, mas a evidência econômica permanece inconclusiva; exposição não resolvida não é falha de execução.', '']
    for title, stage in [('Desenvolvimento2023', report['development']),
                         ('Confirmação2024', report['confirmation']['economic_result'])]:
        if stage is None:
            continue
        lines += ['## '+title, '', f"Denominador integral: {stage['opportunity_denominator']} oportunidades por cenário. Sem piso arbitrário de trades.", '',
                  '| Política | G4: S1 por trimestre | G5: S2 total/DD/capital | Evidência |',
                  '|---|---|---|---|']
        for policy in POLICIES:
            values = stage['policies'][policy]
            lines.append(f"| {policy} | {_status(values['G4'])} | {_status(values['G5'])} | {'principal estrita' if policy == 'P0' else 'contrafactual'} |")
        lines += ['', '| Política | Custo | Braço | Período | Oportunidades | Entradas | PnL marcadoUSD | DDUSD | Comissão | Funding registrado | Funding condicional |',
                  '|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|']
        for scenario in stage['scenarios']:
            for period, values in [('TOTAL', scenario['total'])]+list(scenario['quarters'].items()):
                count = values.get('counts', {})
                opportunities = values.get('opportunities', count.get('opportunities', 0))
                entries = values.get('entries', count.get('entries', 0))
                fields = [scenario['policy'], scenario['bundle'], scenario['arm'], period, str(opportunities), str(entries),
                          _display(values['conclusive_pnl']), _display(values['max_dollar_drawdown']),
                          _display(values.get('commission')), _display(values.get('funding_recorded')),
                          _display(values.get('conditional_funding', values.get('funding_if_still_open')))]
                lines.append('| '+' | '.join(fields)+' |')
        lines += ['', 'Os CSVs preservam os motivos de bloqueio, contadores completos, custos, turnover, exposição e PnL contrafactual. Valores monetários acima são apenas arredondados para exibição.', '']
    lines += ['## Classificação: proxy TP-primeiro', '', 'Estes diagnósticos não são evidência de lucro nem critérios de abertura de2024.', '',
              '| Etapa | Fase | Família | Fit | Treino | Positivos | p disponíveis | Rótulos diagnosticáveis | LL | Brier |',
              '|---|---|---|---|---:|---:|---:|---:|---:|---:|']
    for stage, summary in report['models'].items():
        for phase in summary['phases']:
            for family, values in phase['models'].items():
                scored = values.get('TP_proxy_diagnostics', {})
                support = values['training_support']
                cells = [stage, phase['phase'], family, values['fit_status'], str(support.get('rows', 0)), str(support.get('positive', 0)),
                         str(values.get('available_probabilities', '—')), str(values.get('metric_rows', '—')),
                         str(scored.get('log_loss', '—')), str(scored.get('brier', '—'))]
                lines.append('| '+' | '.join(cells)+' |')
    lines += ['', '## Limitações', '']+['- '+text for text in report['limitations_pt']]
    if report['artifact_hashes']:
        lines += ['', '## Artefatos agregados', '', '| Artefato | Bytes | SHA256 |', '|---|---:|---|']
        lines += [f"| {row['artifact']} | {row['bytes']} | {row['sha256']} |" for row in report['artifact_hashes']]
    return '\n'.join(lines)+'\n'


def aggregate_csv(report):
    """One row per scenario/period: exact rational text, LF and no raw paths."""
    rows = []
    for stage_name, stage in [('development', report['development']), ('confirmation', report['confirmation']['economic_result'])]:
        if stage is None:
            continue
        for scenario in stage['scenarios']:
            for period, values in [('TOTAL', scenario['total'])]+list(scenario['quarters'].items()):
                row = {'stage': stage_name, 'policy': scenario['policy'], 'cost': scenario['bundle'],
                       'arm': scenario['arm'], 'period': period}
                for key, value in sorted(values.items()):
                    if key in ('counts', 'blocked'):
                        row.update({key+'.'+counter: number for counter, number in value.items()})
                    elif key in AMOUNTS:
                        number = _exact(value)
                        row[key] = '' if number is None else str(number)
                    else:
                        row[key] = value
                rows.append(row)
    leading = ['stage', 'policy', 'cost', 'arm', 'period']
    columns = leading+sorted(set().union(*(row.keys() for row in rows))-set(leading))
    output = io.StringIO(newline='')
    writer = csv.DictWriter(output, fieldnames=columns, lineterminator='\n')
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def write_report(report, output):
    """Publish a complete directory atomically; retain interrupted staging outputs."""
    encoded = json.dumps(report, ensure_ascii=False, sort_keys=True, allow_nan=False, indent=2)+'\n'
    contents = {'report.json': encoded, 'report.md': markdown(report), 'aggregates.csv': aggregate_csv(report)}
    directory = Path(output)
    if directory.exists():raise FileExistsError(str(directory))
    import uuid
    staging=directory.with_name(directory.name+'.partial-'+uuid.uuid4().hex)
    staging.mkdir(exist_ok=False)
    result = {}
    for name, content in contents.items():
        path = staging/name
        data = content.encode('utf8')
        with path.open('xb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        result[name] = {'path': str((directory/name).resolve()), 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    fd=os.open(staging,os.O_RDONLY)
    try:os.fsync(fd)
    finally:os.close(fd)
    # Only a complete fsynced directory becomes the public aggregate output.
    # Interrupted attempts remain forensic siblings; they are never adopted.
    staging.rename(directory)
    sync_report_directory(directory)
    return result


def sync_report_directory(directory):
    """Finish publication durability, including after a visible interrupted rename."""
    directory=Path(directory)
    for parent in (directory,directory.parent):
        fd=os.open(parent,os.O_RDONLY)
        try:os.fsync(fd)
        finally:os.close(fd)
