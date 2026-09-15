from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest

from fxnn.economic_dataset import build_dataset, build_labels, verified_records
from fxnn.economic_clock import SessionClockMs
from fxnn.tick_economic_source import SourceRow, digest


def rows(future='1.1'):
    for sequence,i in enumerate([0,1,2,20,21,22,29],1):
        price=Decimal(future if i>=20 else '1')
        yield SourceRow('202201','a'*64,sequence,i*60000,(),lambda p=price:(p,p))


class DatasetTest(unittest.TestCase):
    def test_stream_denominators_future_invariance_and_rebuild(self):
        clock=SessionClockMs(0,10000*60000,[(0,10000*60000)])
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            paths=[root/'a',root/'b',root/'c']
            manifests=[build_dataset(rows(value),clock,0,30*60000,path,{'synthetic':True},min_free=0)
                       for path,value in zip(paths,['1.1','2','1.1'])]
            parsed=[]
            for path,manifest in zip(paths,manifests):
                self.assertEqual(manifest['expected_opportunities'],30)
                self.assertEqual(manifest['counts']['opportunities'],30)
                parsed.append(list(verified_records(path/'opportunities.jsonl',manifest['files']['opportunities.jsonl']['sha256'])))
            self.assertEqual(parsed[0][:21],parsed[1][:21])
            self.assertEqual(manifests[0],manifests[2])
            self.assertEqual(digest(paths[0]/'index/manifest.json'),digest(paths[2]/'index/manifest.json'))
            labels=build_labels(paths[0],digest(paths[0]/'manifest.json'),root/'labels')
            self.assertEqual(labels['counts']['rows'],30)
            self.assertEqual(labels['counts']['unavailable'],30)
            with self.assertRaises(FileExistsError):
                build_dataset(rows(),clock,0,30*60000,paths[0],{},min_free=0)

    def test_content_change_rejected_before_labels(self):
        clock=SessionClockMs(0,10000*60000,[(0,10000*60000)])
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'data'
            build_dataset(rows(),clock,0,30*60000,path,{},min_free=0)
            expected=digest(path/'manifest.json')
            (path/'opportunities.jsonl').write_text('{}\n')
            with self.assertRaisesRegex(ValueError,'fingerprint'):
                build_labels(path,expected,Path(temp)/'labels')


if __name__=='__main__':unittest.main()
