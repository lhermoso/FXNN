from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from fxnn.economic_index import TickIndex, build_index, UncertainRange
from fxnn.economic_clock import SessionClockMs
from fxnn.tick_economic_source import grouped, QuoteGroup, EventKey, Hazard, digest
from test_tick_economic_source import row


class EconomicIndexTests(unittest.TestCase):
    def test_range_count_excludes_offsession_with_partial_blocks(self):
        clock=SessionClockMs(0,100,[(0,30),(40,70),(80,100)])
        groups=[g for g in grouped([row(i+1,i,'1','1.1') for i in range(100)],clock)
                if isinstance(g,QuoteGroup)]
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'index'
            manifest=build_index(groups,[],path,{},block_size=7,min_free=0)
            with TickIndex(path,manifest['contract_sha256'],expected_manifest_sha256=digest(path/'manifest.json')) as index:
                for a,b in [(0,100),(5,87),(31,39),(0,0),(29,41),(79,100)]:
                    self.assertEqual(index.range_count(EventKey(a,0,-1),EventKey(b,0,-1)),
                                     sum(clock.is_open(t) for t in range(a,b)))

    def test_exact_first_hit_marks_and_disk_reopen(self):
        with TemporaryDirectory() as tmp:
            values=['1.00000000000000000000000000001','1.2','1.01','1.3','1.1']
            clock=SessionClockMs(0,100,[(0,100)])
            groups=[g for g in grouped([row(i+1,i,v,str(Decimal(v)+Decimal('.1'))) for i,v in enumerate(values)],clock) if isinstance(g,QuoteGroup)]
            path=Path(tmp)/'index'
            manifest=build_index(groups,[],path,{'synthetic':True},block_size=2,min_free=0)
            with TickIndex(path,manifest['contract_sha256'],expected_manifest_sha256=digest(path/'manifest.json')) as index:
                hit=index.first_crossing(EventKey(0,0,-1),EventKey(5,0,-1),'bid',upper=Fraction(6,5))
                self.assertEqual(hit.timestamp,1)
                exact=Fraction(Decimal(values[0]))
                self.assertEqual(index.first_crossing(EventKey(0,0,-1),EventKey(1,0,-1),'bid',upper=exact).timestamp,0)
                self.assertIsNone(index.first_crossing(EventKey(0,0,-1),EventKey(1,0,-1),'bid',upper=exact+Fraction(1,10**40)))
                summary=index.range_marks(EventKey(0,0,-1),EventKey(5,0,-1),'bid')
                dense=list(map(lambda x:Fraction(Decimal(x)),values))
                self.assertEqual(summary.drop,max(dense[i]-dense[j] for i in range(5) for j in range(i,5)))
                self.assertEqual(summary.rise,max(dense[j]-dense[i] for i in range(5) for j in range(i,5)))
                self.assertTrue(any(b['encoding']=='integer_json' for b in index.manifest['blocks']))
            with self.assertRaises(FileExistsError): build_index(groups,[],path,{},min_free=0)

    def test_hazards_stop_search_and_original_time_predicate(self):
        with TemporaryDirectory() as tmp:
            clock=SessionClockMs(0,200,[(0,200)])
            groups=[g for g in grouped([row(1,100),row(2,99),row(3,100),row(4,101)],clock) if isinstance(g,QuoteGroup)]
            hazard=Hazard(groups[1].key,'out_of_order',groups[1].identity,0,200)
            path=Path(tmp)/'index'; m=build_index(groups,[hazard],path,{},block_size=2,min_free=0)
            with TickIndex(path,m['contract_sha256'],expected_manifest_sha256=digest(path/'manifest.json')) as index:
                self.assertIsNone(index.first_crossing(groups[0].key,EventKey(102,0,-1),'bid',upper=Fraction(1),entry_timestamp=100))
                self.assertEqual(index.first_return(hazard,EventKey(102,0,-1)).timestamp,101)
                with self.assertRaises(UncertainRange): index.range_marks(groups[0].key,EventKey(102,0,-1),'bid')

    def test_random_dense_oracle_and_partial_blocks(self):
        import random
        rng=random.Random(9)
        clock=SessionClockMs(0,1000,[(0,1000)])
        prices=[Decimal(rng.randrange(10000,20000)).scaleb(-4) for _ in range(97)]
        groups=[g for g in grouped([row(i+1,i,str(p),str(p+Decimal('.01'))) for i,p in enumerate(prices)],clock) if isinstance(g,QuoteGroup)]
        for size in (1,3,16,1024):
            with self.subTest(block_size=size),TemporaryDirectory() as tmp:
                path=Path(tmp)/'index'; m=build_index(groups,[],path,{},block_size=size,min_free=0)
                with TickIndex(path,m['contract_sha256'],expected_manifest_sha256=digest(path/'manifest.json'),cache_bytes=200000) as index:
                    for _ in range(80):
                        a,b=sorted([rng.randrange(98),rng.randrange(98)])
                        lower,upper=Fraction(rng.randrange(10000,13000),10000),Fraction(rng.randrange(16000,20000),10000)
                        for side in ('bid','ask'):
                            offset=Fraction(0) if side=='bid' else Fraction(1,100)
                            values=[Fraction(v)+offset for v in prices]
                            expected=next((i for i in range(a,b) if values[i]<=lower or values[i]>=upper),None)
                            hit=index.first_crossing(EventKey(a,0,-1),EventKey(b,0,-1),side,lower,upper)
                            self.assertEqual(None if hit is None else hit.timestamp,expected)
                            summary=index.range_marks(EventKey(a,0,-1),EventKey(b,0,-1),side)
                            if a==b:
                                self.assertIsNone(summary); continue
                            self.assertEqual(summary.drop,max(values[i]-values[j] for i in range(a,b) for j in range(i,b)))
                            self.assertEqual(summary.rise,max(values[j]-values[i] for i in range(a,b) for j in range(i,b)))
                            equity=summary.affine(-1000,Fraction(10000)-Fraction(7,200))
                            self.assertEqual(equity.drop,1000*summary.rise)
                    self.assertLessEqual(index.cache_size,index.cache_limit)
                    before=index.metrics['decoded_blocks']
                    self.assertIsNone(index.first_crossing(EventKey(0,0,-1),EventKey(1000,0,-1),'bid',upper=Fraction(0),entry_timestamp=1000))
                    self.assertEqual(index.metrics['decoded_blocks'],before)

    def test_corruption_no_partial_manifest_and_resource_guards(self):
        from unittest.mock import patch
        import json
        clock=SessionClockMs(0,100,[(0,100)])
        groups=[g for g in grouped([row(1,1)],clock) if isinstance(g,QuoteGroup)]
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'index'
            with patch('fxnn.economic_index.os.fsync',side_effect=OSError('durability failure')):
                with self.assertRaises(OSError): build_index(groups,[],path,{},min_free=0)
            self.assertFalse((path/'manifest.json').exists())
            self.assertTrue((path/'records.bin').exists())
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'index';m=build_index(groups,[],path,{},min_free=0)
            old=digest(path/'manifest.json')
            changed=json.loads((path/'manifest.json').read_text());changed['blocks'][0]['scale']+=1
            (path/'manifest.json').write_text(json.dumps(changed))
            with self.assertRaisesRegex(ValueError,'manifest hash'):
                TickIndex(path,m['contract_sha256'],expected_manifest_sha256=old)
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'index'
            giant=[g for g in grouped([row(1,1,'1e10000','2e10000')],clock) if isinstance(g,QuoteGroup)]
            with self.assertRaisesRegex(ValueError,'precision resources'): build_index(giant,[],path,{},min_free=0)
            self.assertFalse((path/'manifest.json').exists())

    def test_offsession_ambiguous_group_is_not_a_fill(self):
        clock=SessionClockMs(0,100,[(0,10),(50,100)])
        groups=[g for g in grouped([row(1,20),row(2,20,'2','3'),row(3,51)],clock) if isinstance(g,QuoteGroup)]
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'index';m=build_index(groups,[],path,{},min_free=0)
            with TickIndex(path,m['contract_sha256'],expected_manifest_sha256=digest(path/'manifest.json')) as index:
                self.assertEqual(index.first_entry(EventKey(0,3,0),60).timestamp,51)
                self.assertIsNone(index.first_entry(EventKey(0,3,0),51))
                self.assertEqual(index.first_return(Hazard(EventKey(0,1,0),'gap',()),EventKey(90,0,-1)).timestamp,51)

    def test_last_quote_full_key_and_bounded_fixture_iterator(self):
        clock=SessionClockMs(0,200,[(0,50),(100,200)])
        groups=[g for g in grouped([row(1,1),row(2,2),row(3,50),row(4,101)],clock) if isinstance(g,QuoteGroup)]
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'index';m=build_index(groups,[],path,{},block_size=2,min_free=0)
            with TickIndex(path,m['contract_sha256'],expected_manifest_sha256=digest(path/'manifest.json')) as index:
                quote=index.last_quote(EventKey(0,0,-1),EventKey(101,0,-1))
                self.assertEqual(quote.timestamp,2);self.assertEqual(quote.first_sequence,2)
                self.assertEqual(index.last_quote(EventKey(0,0,-1),EventKey(102,0,-1)).timestamp,101)
                self.assertIsNone(index.last_quote(EventKey(2,5,0),EventKey(100,0,-1)))
                self.assertEqual([g.first_sequence for g in index.iter_groups(EventKey(0,0,-1),EventKey(102,0,-1))],[1,2,3,4])
                with self.assertRaisesRegex(ValueError,'cap'):
                    list(index.iter_groups(EventKey(0,0,-1),EventKey(102,0,-1),max_groups=2))


    def test_tiny_scale_resource_failure_before_publish(self):
        clock=SessionClockMs(0,100,[(0,100)])
        groups=[g for g in grouped([row(1,1,'1e-10000','2e-10000')],clock) if isinstance(g,QuoteGroup)]
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'index'
            with self.assertRaisesRegex(ValueError,'scale exceeds'):
                build_index(groups,[],path,{},min_free=0)
            self.assertFalse((path/'manifest.json').exists())
