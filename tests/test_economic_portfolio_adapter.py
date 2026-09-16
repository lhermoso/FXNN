"""Synthetic-only adapter tests; no source payloads, models or real supervisor."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fxnn.economic_portfolio_adapter import portfolio_segment,MonthlyPredictions,quarter_periods,collect_checkpoint
from fxnn.economic_clock import SessionClockMs,utc_ms
from fxnn.economic_lifecycle import fingerprint,atomic_json
from fxnn.economic_index import build_index,TickIndex
from fxnn.economic_report import evaluate_portfolios


def ms(value):return utc_ms(value+'T00:00:00+00:00')


class AdapterTests(unittest.TestCase):
    def fixture(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);root=Path(temp.name).resolve()
        config=dict(development_utc=['2022-01-01','2024-01-01'],development_portfolio_utc=['2023-04-01','2024-01-01'],
                    confirmation_utc=['2024-01-01','2025-01-01'],calendar_utc=['2022-01-01','2025-01-10'],
                    index={'cache_bytes':256*1024**2},folds=[])
        for name,start,end in [('2023Q2','2023-04-01','2023-07-01'),('2023Q3','2023-07-01','2023-10-01'),('2023Q4','2023-10-01','2024-01-01')]:
            config['folds'].append(dict(name=name,test_start=start+'T00:00:00+00:00',test_end=end+'T00:00:00+00:00'))
        times=[ms(v) for v in ('2023-04-01','2023-07-01','2023-10-01')]
        clock=SessionClockMs(ms('2022-01-01'),ms('2025-01-10'),[(t,t+60000) for t in times])
        data=root/'data';folder=data/'dataset';folder.mkdir(parents=True);(data/'labels').mkdir()
        science=root/'science';science.write_text('synthetic source code')
        files={'science':fingerprint(science)}
        snapshot=dict(config=config,S='a'*64,files=files,guard='UNOPENED',sealed=False,P=None,effects={})
        supervisor=SimpleNamespace(root=root/'canonical',read=lambda:copy.deepcopy(snapshot))
        opp=[dict(id=f'economic_ticks_v1:{t}',decision_ms=t,side=0,eligible=False,price_volatility=None,
                  deadline_ms=t+1,earliest_input=None,history_valid=False,observed_history=0,segment=0) for t in times]
        (folder/'opportunities.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in opp))
        (folder/'bars.jsonl').write_text('');(folder/'warmup.json').write_text('{}')
        idx=build_index([],[],folder/'index',{'synthetic':True},min_free=0,block_size=2)
        artifacts={name:{k:v for k,v in fingerprint(folder/name).items() if k!='path'}
                   for name in ['opportunities.jsonl','bars.jsonl','warmup.json','index/manifest.json']}
        dataset=dict(experiment='economic_ticks_v1',start_ms=ms('2022-01-01'),end_ms=ms('2024-01-01'),
                     files=artifacts,expected_opportunities=3,index_contract_sha256=idx['contract_sha256'],
                     contract=dict(experiment='economic_ticks_v1',config=config,preregistered_sha='b'*40,scientific_files=files))
        atomic_json(folder/'manifest.json',dataset)
        atomic_json(data/'labels/manifest.json',dict(dataset_manifest_sha256=fingerprint(folder/'manifest.json')['sha256']))
        evidence=dict(dataset=fingerprint(folder/'manifest.json'),labels=fingerprint(data/'labels/manifest.json'),
                      preregistered_sha='b'*40,confirmation_access=False)
        op=root/'operational.jsonl';op.write_text(''.join(json.dumps(dict(id=r['id'],decision_ms=r['decision_ms'],probability=None,model_available=True))+'\n' for r in opp))
        return root,config,supervisor,data,evidence,fingerprint(op),clock

    def test_report_compatible_totals_quarters_and_readonly_replay(self):
        root,config,supervisor,data,evidence,op,clock=self.fixture()
        with patch('fxnn.economic_portfolio_adapter.SessionClockMs.weekly',return_value=clock):
            result=portfolio_segment(config,supervisor,data,evidence,op,root/'portfolio')
            self.assertEqual(len(result['scenarios']),12)
            for scenario in result['scenarios']:
                self.assertEqual(scenario['total']['counts']['opportunities'],3)
                self.assertEqual([q['opportunities'] for q in scenario['quarters'].values()],[1,1,1])
                self.assertTrue(scenario['total']['arm_model_available'])
            self.assertFalse(evaluate_portfolios(result)['promotion'])
            before={str(p):(p.stat().st_mtime_ns,p.read_bytes()) for p in root.rglob('*') if p.is_file()}
            replay=portfolio_segment(config,supervisor,data,evidence,op,root/'portfolio',replay=True)
            after={str(p):(p.stat().st_mtime_ns,p.read_bytes()) for p in root.rglob('*') if p.is_file()}
            self.assertEqual(before,after)
            self.assertEqual(result['scenarios'],replay['scenarios'])
            self.assertTrue(replay['replay_verified'])

    def test_collect_checkpoint_uses_no_market_query(self):
        root,config,supervisor,data,evidence,op,clock=self.fixture()
        with patch('fxnn.economic_portfolio_adapter.SessionClockMs.weekly',return_value=clock):
            portfolio_segment(config,supervisor,data,evidence,op,root/'portfolio')
        manifest=json.loads((root/'portfolio/portfolio-manifest.json').read_text())
        ds=json.loads((data/'dataset/manifest.json').read_text())
        with TickIndex(data/'dataset/index',ds['index_contract_sha256'],expected_manifest_sha256=ds['files']['index/manifest.json']['sha256']) as index:
            with patch.object(index,'first_entry',side_effect=AssertionError('market query')),patch.object(index,'range_count',side_effect=AssertionError('market query')),patch.object(index,'last_quote',side_effect=AssertionError('market query')):
                result=collect_checkpoint(manifest,index,clock,manifest['contract']['scientific'],quarter_periods(config,False))
        self.assertEqual(len(result['scenarios']),12)

    def test_missing_probability_or_wrong_identity_fails_before_output(self):
        for bad in ['missing','identity']:
            root,config,supervisor,data,evidence,op,clock=self.fixture()
            p=Path(op['path']);rows=p.read_text().splitlines()
            if bad=='missing':rows=rows[:-1]
            else:
                r=json.loads(rows[0]);r['id']='wrong';rows[0]=json.dumps(r)
            p.write_text('\n'.join(rows)+'\n')
            with patch('fxnn.economic_portfolio_adapter.SessionClockMs.weekly',return_value=clock):
                with self.assertRaises(ValueError):portfolio_segment(config,supervisor,data,evidence,fingerprint(p),root/'portfolio')
            self.assertFalse((root/'portfolio').exists())

    def test_changed_op_dataset_or_config_refused(self):
        for bad in ['operational','dataset','config']:
            root,config,supervisor,data,evidence,op,clock=self.fixture()
            if bad=='operational':Path(op['path']).write_text('bad')
            elif bad=='dataset':(data/'dataset/warmup.json').write_text('changed')
            else:config=copy.deepcopy(config);config['threshold']=.7
            with patch('fxnn.economic_portfolio_adapter.SessionClockMs.weekly',return_value=clock):
                with self.assertRaises(ValueError):portfolio_segment(config,supervisor,data,evidence,op,root/'portfolio')
            self.assertFalse((root/'portfolio').exists())

    def test_confirmation_closed_before_dataset_access(self):
        root,config,supervisor,data,evidence,op,clock=self.fixture()
        with self.assertRaisesRegex(ValueError,'frozen'):portfolio_segment(config,supervisor,data,evidence,op,root/'portfolio',confirmation=True)
        self.assertFalse((root/'portfolio').exists())

if __name__=='__main__':unittest.main(verbosity=2)
