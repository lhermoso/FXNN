"""Explicit tiny financial fixtures; no fits, market data or ledger access."""
import unittest
from fxnn.economic_report import tri_all


class DecisionTests(unittest.TestCase):
    def test_determinate_failure_dominates_unknown(self):
        self.assertIs(tri_all([None, False]), False)
        self.assertIsNone(tri_all([None, True]))
        self.assertIs(tri_all([True, True]), True)

import copy
import csv
from fractions import Fraction as F
import hashlib
import io
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

from fxnn import economic_report as report


def fixture(confirmation=False):
    quarters = report.CONFIRMATION_QUARTERS if confirmation else report.DEVELOPMENT_QUARTERS
    scenarios = []
    for policy in report.POLICIES:
        for cost in report.BUNDLES:
            for arm in report.ARMS:
                amount = F(20 if arm == 'filtered' else 10)
                quarter = {'conclusive_pnl': amount, 'scenario_pnl': amount,
                           'max_dollar_drawdown': F(100), 'capital_breach': False,
                           'model_available': True, 'opportunities': 100, 'entries': 1, 'exits': 1,
                           'blocked': {'occupied_or_unresolved': 10, 'filter_rejected': 20,
                                       'probability_unavailable': 5, 'model_unavailable': 2},
                           'commission': F(7,100), 'funding_recorded': F(1,3),
                           'conditional_funding': F(2,3), 'turnover_eur': F(2000), 'turnover_usd': F(2200),
                           'recorded_cashflow': amount, 'realized_recorded': amount,
                           'slippage_attribution_only': F(1,50), 'wall_exposure_ms': 500,
                           'open_exposure_ms': 400}
                total = {'state': 'ENDED', 'conclusive_pnl': amount*len(quarters), 'scenario_pnl': amount*len(quarters),
                         'max_dollar_drawdown': F(100), 'capital_breach': False,
                         'arm_model_available': True, 'counts': {'opportunities': 100*len(quarters),
                            'entries': len(quarters), 'exits': len(quarters), 'entry_expired': 3,
                            'opportunity_model_unavailable': 2*len(quarters),
                            'opportunity_causal_unavailable': 7, 'unresolved_at_end': 0},
                         'blocked': {k:v*len(quarters) for k,v in quarter['blocked'].items()},
                         'known_cash': F(10000)+amount*len(quarters), 'funding_if_still_open': F(2),
                         'funding_recorded': F(1), 'commission': F(7,100)*len(quarters),
                         'turnover_eur': F(2000)*len(quarters), 'turnover_usd': F(2200)*len(quarters),
                         'slippage_attribution_only': F(1,50)*len(quarters),
                         'wall_exposure_ms': 500*len(quarters), 'open_exposure_ms': 400*len(quarters)}
                scenarios.append({'policy': policy, 'bundle': cost, 'arm': arm, 'total': total,
                                  'quarters': {q: copy.deepcopy(quarter) for q in quarters}})
    return {'scenarios': scenarios}


def scenario(portfolios, policy='P0', cost='S1', arm='filtered'):
    return next(r for r in portfolios['scenarios'] if (r['policy'],r['bundle'],r['arm']) == (policy,cost,arm))


class PromotionTests(unittest.TestCase):
    def build(self, dev=None, conf=None, status='COMPLETED'):
        return report.build_report(None, None, fixture() if dev is None else dev,
            confirmation={'execution_status': status, 'portfolios': fixture(True) if conf is None else conf})

    def test_pass_requires_both_development_and_completed_confirmation(self):
        self.assertEqual(self.build()['combined_decision'], 'PAPER_TRADING_PLANNING_CONDITIONAL')
        no_confirm = report.build_report(None, None, fixture())
        self.assertEqual(no_confirm['combined_decision'], 'EXPLORATION_ONLY')
        self.assertEqual(no_confirm['confirmation']['execution_status'], 'UNOPENED')
        self.assertIn('não realizado', no_confirm['confirmation']['execution_description_pt'])
        self.assertFalse(no_confirm['opening_authorization'])

    def test_positive_confirmation_never_erases_negative_development(self):
        dev = fixture()
        scenario(dev)['quarters']['2023Q2']['conclusive_pnl'] = F(-1)
        result = self.build(dev=dev)
        self.assertEqual(result['combined_decision'], 'REJECT_PROMOTION')
        self.assertIs(result['development']['promotion'], False)
        self.assertIs(result['confirmation']['promotion'], True)

    def test_known_failure_dominates_uncertain_other_stage_in_both_directions(self):
        dev, conf = fixture(), fixture(True)
        scenario(dev)['quarters']['2023Q2']['conclusive_pnl'] = F(-1)
        scenario(conf)['quarters']['2024Q1']['conclusive_pnl'] = None
        self.assertEqual(self.build(dev, conf)['combined_decision'], 'REJECT_PROMOTION')
        dev, conf = fixture(), fixture(True)
        scenario(dev)['quarters']['2023Q2']['conclusive_pnl'] = None
        scenario(conf)['quarters']['2024Q1']['conclusive_pnl'] = F(0)
        self.assertEqual(self.build(dev, conf)['combined_decision'], 'REJECT_PROMOTION')

    def test_zero_available_trade_result_fails_strict_positive_no_support_floor(self):
        dev = fixture()
        record = scenario(dev)
        record['quarters']['2023Q2']['entries'] = 0
        record['quarters']['2023Q2']['conclusive_pnl'] = F(0)
        self.assertIs(report.evaluate_portfolios(dev)['promotion'], False)
        positive = fixture()
        for record in positive['scenarios']:
            record['total']['counts']['entries'] = 1
        self.assertIs(report.evaluate_portfolios(positive)['promotion'], True)

    def test_unavailable_comparison_is_not_numeric_zero(self):
        dev = fixture()
        q = scenario(dev)['quarters']['2023Q2']
        q['model_available'] = False
        q['conclusive_pnl'] = F(0)
        result = self.build(dev=dev)
        self.assertEqual(result['combined_decision'], 'EXPLORATION_ONLY')
        self.assertIsNone(result['development']['policies']['P0']['G4'])

    def test_p1_success_cannot_rescue_strict_p0(self):
        dev = fixture()
        scenario(dev)['quarters']['2023Q2']['conclusive_pnl'] = None
        result = self.build(dev=dev)
        self.assertIs(result['development']['policies']['P1']['promotion'], True)
        self.assertEqual(result['combined_decision'], 'EXPLORATION_ONLY')
        scenario(dev)['quarters']['2023Q2']['conclusive_pnl'] = F(-1)
        self.assertEqual(self.build(dev=dev)['combined_decision'], 'REJECT_PROMOTION')

    def test_stress_drawdown_exact_boundary_and_capital_breach_unknown(self):
        dev = fixture()
        stress = scenario(dev, cost='S2')['total']
        stress['max_dollar_drawdown'] = F(500)
        self.assertIs(report.evaluate_portfolios(dev)['promotion'], True)
        stress['max_dollar_drawdown'] += F(1,10**20)
        self.assertIs(report.evaluate_portfolios(dev)['promotion'], False)
        stress.update(max_dollar_drawdown=None, conclusive_pnl=None, capital_breach=True)
        self.assertIs(report.evaluate_portfolios(dev)['promotion'], False)

    def test_annual_confirmation_is_additional_criterion(self):
        conf = fixture(True)
        scenario(conf)['total']['conclusive_pnl'] = F(-1)
        result = self.build(conf=conf)
        self.assertIs(result['confirmation']['economic_result']['policies']['P0']['G4'], True)
        self.assertEqual(result['combined_decision'], 'REJECT_PROMOTION')

    def test_completed_unresolved_is_not_incomplete_execution(self):
        conf = fixture(True)
        item = scenario(conf)
        item['total'].update(conclusive_pnl=None, max_dollar_drawdown=None)
        item['total']['counts']['unresolved_at_end'] = 1
        item['quarters']['2024Q4']['conclusive_pnl'] = None
        result = self.build(conf=conf)
        self.assertEqual(result['confirmation']['execution_status'], 'COMPLETED')
        self.assertTrue(result['confirmation']['completed_with_uncertainty'])
        self.assertEqual(result['combined_decision'], 'EXPLORATION_ONLY')
        self.assertIn('avaliação foi concluída', report.markdown(result))

    def test_opened_positive_or_incomplete_positive_never_pass(self):
        for status in ('OPENING', 'OPENED', 'INCOMPLETE'):
            with self.subTest(status=status):
                result = self.build(status=status)
                self.assertEqual(result['combined_decision'], 'EXPLORATION_ONLY')
                self.assertEqual(result['confirmation']['execution_status'], status)

    def test_missing_scenario_quarter_or_different_denominator_rejected(self):
        for mode in ('scenario', 'quarter', 'denominator'):
            dev = fixture()
            if mode == 'scenario':
                dev['scenarios'].pop()
            elif mode == 'quarter':
                scenario(dev)['quarters'].pop('2023Q2')
            else:
                scenario(dev)['total']['counts']['opportunities'] -= 1
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                report.evaluate_portfolios(dev)

    def test_unopened_cannot_smuggle_confirmation_and_complete_needs_evidence(self):
        with self.assertRaises(ValueError):
            self.build(status='UNOPENED')
        with self.assertRaises(ValueError):
            report.build_report(None,None,fixture(),confirmation={'execution_status':'COMPLETED'})

    def test_missing_primary_does_not_hide_known_filtered_loss(self):
        dev = fixture()
        scenario(dev, arm='primary')['quarters']['2023Q2']['model_available'] = False
        scenario(dev)['quarters']['2023Q2']['conclusive_pnl'] = F(-1)
        self.assertIs(report.evaluate_portfolios(dev)['promotion'], False)


class OutputTests(unittest.TestCase):
    def test_all_scenarios_windows_costs_counts_exact_csv_lf(self):
        result = report.build_report(None, None, fixture(),
            confirmation={'execution_status':'COMPLETED','portfolios':fixture(True)})
        data = report.aggregate_csv(result)
        self.assertNotIn('\r', data)
        rows = list(csv.DictReader(io.StringIO(data)))
        self.assertEqual(len({(r['policy'],r['cost'],r['arm']) for r in rows}), 12)
        self.assertEqual({r['period'] for r in rows}, {'TOTAL', *report.DEVELOPMENT_QUARTERS, *report.CONFIRMATION_QUARTERS})
        self.assertEqual(len(rows), 12*(4+5))
        for key in ('conditional_funding','funding_if_still_open','blocked.probability_unavailable',
                    'counts.entry_expired','turnover_usd'):
            self.assertIn(key,rows[0])
        self.assertIn('2/3', {r['conditional_funding'] for r in rows})

    def test_publish_json_md_csv_hashes_no_paths_raw_arrays_or_journals(self):
        dev = fixture()
        scenario(dev)['total'].update(raw_prices=[1,2,3], journal_head='privatejournal', path='/private/market.csv')
        artifacts = {'aggregate input': {'path':'/private/market.csv','bytes':17,'sha256':'a'*64}}
        result = report.build_report(None,None,dev,artifacts=artifacts)
        with tempfile.TemporaryDirectory(prefix='economic-report-synthetic-') as directory:
            output = Path(directory)/'report'
            manifest = report.write_report(result,output)
            self.assertEqual(set(manifest), {'report.json','report.md','aggregates.csv'})
            for name, item in manifest.items():
                data = (output/name).read_bytes()
                self.assertEqual(item['sha256'],hashlib.sha256(data).hexdigest())
                self.assertNotIn(b'/private',data)
                self.assertNotIn(b'raw_prices',data)
                self.assertNotIn(b'privatejournal',data)
                self.assertNotIn(b'NaN',data)
            self.assertEqual(json.loads((output/'report.json').read_text()),result)
            with self.assertRaises(FileExistsError):
                report.write_report(result,output)

    def test_unresolved_does_not_substitute_realized_or_scenario_pnl(self):
        dev = fixture()
        item = scenario(dev)
        item['quarters']['2023Q2'].update(conclusive_pnl=None, realized_recorded=F(999), scenario_pnl=F(999))
        result = report.build_report(None,None,dev)
        values = scenario(result['development'])['quarters']['2023Q2']
        self.assertIsNone(values['conclusive_pnl'])
        self.assertEqual(values['scenario_pnl'], {'numerator':999,'denominator':1})
        self.assertIsNone(result['development']['promotion'])

    def test_reject_nonfinite_and_float_money(self):
        for number in (float('nan'), float('inf'), 0.1):
            dev = fixture()
            scenario(dev)['total']['conclusive_pnl'] = number
            with self.subTest(number=number), self.assertRaises(ValueError):
                report.evaluate_portfolios(dev)

    def test_model_proxy_metrics_separate_no_technical_gate_inference(self):
        metrics = {'rows':100,'available_probabilities':80,'metric_rows':20,'proxy_unobserved_by_boundary':80,
                   'absence_counts':{'available':80,'model_unavailable':20},
                   'score':{'log_loss':.1,'brier':.01,'roc_auc':1.,'average_precision':1.,
                            'support':{'rows':20,'positive':10,'negative':10},
                            'reliability_deciles':[]}}
        models = {'phases':[{'phase':{'name':'2023Q2:refit'},'families':{
            f:{'fit':{'status':'succeeded','support':{'rows':2,'positive':1,'negative':1}},
               'metrics':metrics, 'predictions':{'path':'/private/predictions.npz'}}
            for f in ('constant','logistic')}}]}
        final = copy.deepcopy(models)
        final['phases'][0]['families']['logistic']['fit'].update(status='technically_unavailable',reason='logistic_requires_two_classes')
        result = report.build_report(models, final, fixture())
        self.assertIs(result['development']['promotion'],True)
        self.assertEqual(result['combined_decision'],'EXPLORATION_ONLY')
        self.assertFalse(result['models']['development']['economic_evidence'])
        self.assertTrue(result['technical_T1_T5_owned_by_supervisor'])
        self.assertIn('Classificação: proxy',report.markdown(result))
        self.assertNotIn('/private',json.dumps(result))


class AccountAdapterTests(unittest.TestCase):
    def test_actual_twelve_accounts_zero_signal_full_denominator(self):
        from fxnn.economic_account import make_portfolios, Key, Opportunity
        class Clock:
            def active(self, time): return True
            def coordinate(self, time): return time
            def inverse(self, time, duration): return time+duration
        accounts = make_portfolios(Clock(), 0, 300000)
        for account in accounts.values():
            account.process(Key(0,0), 'snapshot', 'initial')
            for number, name in enumerate(('middle1','middle2','final')):
                account.process(Key(number*100000+1,3), 'decision',
                                Opportunity(str(number),0,F(1),number*100000+50000))
                account.process(Key((number+1)*100000,0), 'snapshot', name)
            account.process(Key(300000,5), 'end')
        source = report.collect_portfolios(accounts,
            [('2023Q2','initial','middle1'),('2023Q3','middle1','middle2'),('2023Q4','middle2','final')])
        result = report.evaluate_portfolios(source)
        self.assertEqual(len(result['scenarios']),12)
        self.assertEqual(result['opportunity_denominator'],3)
        self.assertIs(result['promotion'],False)
        self.assertIs(source['account_diagnostics']['P0']['s2_positive_and_drawdown'],False)
        self.assertEqual(scenario(result)['total']['blocked']['no_primary_signal'],3)



if __name__ == '__main__':
    unittest.main()
