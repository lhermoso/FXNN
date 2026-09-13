"""Predeclared nested walk-forward baseline. No financial backtest or live orders."""
import argparse
import csv
import hashlib
import json
import platform
import time
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import numpy as np
import sklearn
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, log_loss, roc_auc_score
from sklearn.preprocessing import StandardScaler

from .features import LOOKBACK, build_features, orient_features
from .labeling import Candle
from .temporal import split_before, uniqueness_weights


@dataclass
class Dataset:
    X: np.ndarray
    y: np.ndarray
    starts: np.ndarray
    ends: np.ndarray
    info_ends: np.ndarray
    entry_indices: np.ndarray
    sides: np.ndarray
    names: list[str]
    groups: dict[str,list[int]]
    dropped_warmup: int


def epoch(value):
    parsed = datetime.fromisoformat(value)
    if parsed.utcoffset() is None:
        raise ValueError('Timezone-aware timestamp required')
    return int(parsed.timestamp())


def load_dataset(candles_path, labels_path):
    summary=json.loads((labels_path.parent/'summary.json').read_text())
    if summary['input_sha256'] != hashlib.sha256(candles_path.read_bytes()).hexdigest():
        raise ValueError('Labels do not match candle file hash')
    expected={'pip_size':'0.0001','take_profit_pips':'50','stop_loss_pips':'20',
              'max_hold':'3 days, 0:00:00','bar_duration':'0:01:00'}
    if summary['config']!=expected:
        raise ValueError('Baseline requires EURUSD M1 50/20/72h label configuration')
    with candles_path.open() as f:
        candles=[Candle(datetime.fromisoformat(r['timestamp']),*(Decimal(r[k]) for k in ('open','high','low','close'))) for r in csv.DictReader(f)]
    frame=build_features(candles)
    indices=[]; sides=[]; starts=[]; ends=[]; labels=[]; seen=set(); dropped=0
    with labels_path.open() as f:
        for row in csv.DictReader(f):
            i=int(row['entry_index']); side={'long':1,'short':-1}[row['side']]
            if not 0<=i<len(candles) or (i,side) in seen:
                raise ValueError('Invalid or duplicate labeled entry')
            seen.add((i,side))
            if row['outcome'] not in ('take_profit','stop_loss','timeout') or int(row['label'])!=int(row['outcome']=='take_profit'):
                raise ValueError('Non-conclusive or inconsistent label')
            start,end=epoch(row['entry_time']),epoch(row['end_time'])
            if start!=int(candles[i].timestamp.timestamp()) or not start<end<=start+72*3600:
                raise ValueError('Label time mismatch')
            if not frame.valid[i]:
                dropped+=1; continue
            indices.append(i); sides.append(side); starts.append(start); ends.append(end); labels.append(int(row['label']))
    if len(seen)!=summary['usable_labels']:
        raise ValueError('Use entire all_trades.csv, not a retrospectively selected subset')
    order=np.lexsort((np.asarray(sides),np.asarray(starts)))
    indices=np.asarray(indices,dtype=np.int64)[order]; sides=np.asarray(sides)[order]
    starts=np.asarray(starts,dtype=np.int64)[order]; ends=np.asarray(ends,dtype=np.int64)[order]
    return Dataset(orient_features(frame,indices,sides),np.asarray(labels)[order],starts,ends,
                   starts+72*3600,indices,sides,frame.names,frame.groups,dropped)


class Baseline:
    def fit(self,X,y,weights):
        self.prior=float(np.average(y,weights=weights))
        self.model=None
        if X.shape[1] and len(np.unique(y))>1:
            self.scaler=StandardScaler().fit(X,sample_weight=weights)
            self.model=LogisticRegression(C=1.0,max_iter=1000,random_state=0)
            with warnings.catch_warnings():
                warnings.simplefilter('error',ConvergenceWarning)
                self.model.fit(self.scaler.transform(X),y,sample_weight=weights)
        return self

    def predict(self,X):
        if self.model is None:return np.full(len(X),self.prior)
        return self.model.predict_proba(self.scaler.transform(X))[:,1]


def metrics(y,p):
    two=len(np.unique(y))>1
    scores={'rows':len(y),'positives':int(y.sum()),'log_loss':float(log_loss(y,p,labels=[0,1])),
            'brier':float(np.mean((p-y)**2)),
            'average_precision':float(average_precision_score(y,p)) if y.sum() else None,
            'roc_auc':float(roc_auc_score(y,p)) if two else None}
    scores['thresholds']={}
    for threshold in (.3,.4,.5):
        selected=p>=threshold
        tp=int(y[selected].sum()); n=int(selected.sum())
        scores['thresholds'][str(threshold)]={'signals':n,'true_positives':tp,'false_positives':n-tp,
                                            'precision':tp/n if n else None,'recall':tp/int(y.sum()) if y.sum() else None}
    return scores


def group_importance(model,X,y,groups,repeats=3,seed=0,block_size=128):
    if len(y)<2 or repeats<1 or block_size<1:raise ValueError('Insufficient permutation data/settings')
    rng=np.random.default_rng(seed)
    baseline=float(log_loss(y,model.predict(X),labels=[0,1]))
    blocks=[np.arange(i,min(i+block_size,len(y))) for i in range(0,len(y),block_size)]
    report={}
    for name,columns in groups.items():
        changes=[]
        for _ in range(repeats):
            permutation=np.concatenate([blocks[i] for i in rng.permutation(len(blocks))])
            shuffled=X.copy(); shuffled[:,columns]=X[permutation][:,columns]
            changes.append(float(log_loss(y,model.predict(shuffled),labels=[0,1]))-baseline)
        report[name]={'mean_log_loss_increase':float(np.mean(changes)),
                      'std_log_loss_increase':float(np.std(changes)),'repeats':changes}
    return report


def run_fold(data,year,month):
    def boundary(m):return int(datetime(year,m,1,tzinfo=timezone.utc).timestamp())
    outer_start,outer_end=boundary(month),boundary(month+1)
    inner_start=boundary(month-1)
    train,validation=split_before(data.starts,data.info_ends,inner_start,outer_start)
    refit,test=split_before(data.starts,data.info_ends,outer_start,outer_end)
    if min(len(train),len(validation),len(refit),len(test))<100:
        raise ValueError('Fold lacks at least 100 examples per partition')
    weights=uniqueness_weights(data.starts[train],data.ends[train])
    initial=Baseline().fit(data.X[train],data.y[train],weights)
    importance=group_importance(initial,data.X[validation],data.y[validation],data.groups,seed=month)
    retained=[name for name,item in importance.items() if item['mean_log_loss_increase']>0]
    columns=sorted(c for name in retained for c in data.groups[name])
    refit_weights=uniqueness_weights(data.starts[refit],data.ends[refit])
    full=Baseline().fit(data.X[refit],data.y[refit],refit_weights)
    selected=Baseline().fit(data.X[refit][:,columns],data.y[refit],refit_weights)
    prediction=selected.predict(data.X[test][:,columns])
    report={'outer_month':f'{year}-{month:02}','inner_month':f'{year}-{month-1:02}',
            'inner_train_rows':len(train),'inner_validation_rows':len(validation),'refit_rows':len(refit),
            'purged_refit_rows':int((data.starts<outer_start).sum())-len(refit),
            'last_train_information_time':datetime.fromtimestamp(int(data.info_ends[refit].max()),timezone.utc).isoformat(),
            'test_start':datetime.fromtimestamp(outer_start,timezone.utc).isoformat(),
            'selected_groups':retained,'selected_features':[data.names[c] for c in columns],
            'inner_importance':importance,
            'constant':metrics(data.y[test],np.full(len(test),full.prior)),
            'all_features':metrics(data.y[test],full.predict(data.X[test])),
            'selected_features_model':metrics(data.y[test],prediction),
            'weight_min':float(refit_weights.min()),'weight_max':float(refit_weights.max())}
    return report,test,prediction


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candles',type=Path,default=Path('data/histdata/EURUSD/EURUSD_2025_m1_bid_utc.csv'))
    parser.add_argument('--labels',type=Path,default=Path('output/eurusd_2025/all_trades.csv'))
    parser.add_argument('--output',type=Path,default=Path('output/research_v1'))
    args=parser.parse_args(); started=time.perf_counter()
    if args.output.exists() and any(args.output.iterdir()):
        parser.error('Experiment output already exists; choose a new directory to preserve research history')
    data=load_dataset(args.candles,args.labels)
    args.output.mkdir(parents=True,exist_ok=True)
    reports=[]
    with (args.output/'predictions.csv').open('w',newline='') as stream:
        writer=csv.writer(stream); writer.writerow(['fold','entry_index','side','entry_time','label','probability'])
        for month in (7,8,9):
            report,test,prediction=run_fold(data,2025,month); reports.append(report)
            for i,p in zip(test,prediction):
                writer.writerow([report['outer_month'],data.entry_indices[i],int(data.sides[i]),
                                 datetime.fromtimestamp(int(data.starts[i]),timezone.utc).isoformat(),int(data.y[i]),float(p)])
            print(f"{report['outer_month']}: {len(test)} test rows; selected={report['selected_groups']}",flush=True)
    final={'experiment':'research_v1','dataset_rows_after_feature_warmup':len(data.y),
           'dropped_feature_warmup_or_gaps':data.dropped_warmup,'feature_names':data.names,
           'features':len(data.names),'folds':reports,'holdout':'2025-10 through 2025-12 not modeled',
           'versions':{'python':platform.python_version(),'numpy':np.__version__,'sklearn':sklearn.__version__},
           'hashes':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (args.candles,args.labels)},
           'source_hashes':{p.name:hashlib.sha256(p.read_bytes()).hexdigest()
                            for p in sorted(Path(__file__).parent.glob('*.py'))},
           'seconds':round(time.perf_counter()-started,3),
           'interpretation':'Conditional classification on conclusive labels only. No execution, no costs, no profit claim.',
           'protocol':{'months':[7,8,9],'horizon_hours':72,'buffer_minutes':LOOKBACK,
                       'permutation_repeats':3,'permutation_block_rows':128,'logistic_C':1.0,
                       'selection':'inner grouped permutation mean log-loss increase >0'}}
    (args.output/'report.json').write_text(json.dumps(final,indent=2)+'\n')
    print(json.dumps({k:v for k,v in final.items() if k not in ('folds','feature_names')},indent=2))


if __name__=='__main__':main()
