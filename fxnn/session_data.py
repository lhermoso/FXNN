"""Observed-only labels/features with a session clock and tolerated short gaps."""
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal

import numpy as np

from .features import LOOKBACK, build_features, orient_features
from .indexed import BarrierIndex
from .labeling import Config, Trade, validate_candles
from .research import Dataset
from .protocol import utc_epoch


def session_features(candles, breaks):
    """Same formulas on trailing observed candles; no synthetic prices or entries."""
    frame=build_features(candles)
    breaks=np.asarray(breaks,dtype=bool)
    if len(breaks)!=len(candles):raise ValueError('Break mask misaligned')
    n=len(candles);i=np.arange(n);left=np.maximum(0,i-LOOKBACK)
    prefix=np.concatenate(([0],np.cumsum(breaks)))
    frame.valid=(i>=LOOKBACK)&(prefix[i+1]-prefix[left+1]==0)&np.isfinite(frame.values).all(axis=1)
    return frame


def censor_times(stamps, clock, threshold):
    """Censor when the threshold number of missing session minutes has elapsed.

    Uses only absence through the fifteenth missing session minute; never needs
    the eventual return quote or its price. The event time is the boundary after
    that fifteenth minute. Holidays outside weekly closure count as absence.
    """
    gaps=clock.missing_open_minutes(stamps)
    barriers=np.full(len(stamps),np.iinfo(np.int64).max,dtype=np.int64)
    long=np.flatnonzero(gaps>=threshold)
    if len(long):
        barriers[long]=clock.deadlines(stamps[long],threshold+1)
    # Trailing absence is NOT assumed observed: end of file censors immediately.
    barriers[-1]=stamps[-1]+60
    return np.minimum.accumulate(barriers[::-1])[::-1]


def session_labels(candles, clock, threshold=15, horizon=4320):
    config=Config(Decimal('.0001'))
    validate_candles(candles,config)
    if type(threshold)is not int or threshold<1:raise ValueError('Invalid gap threshold')
    stamps=np.asarray([int(c.timestamp.timestamp()) for c in candles],dtype=np.int64)
    if not len(stamps):return [],np.array([],dtype=np.int64)
    deadlines=clock.deadlines(stamps,horizon)
    censored_at=censor_times(stamps,clock,threshold)
    tree=BarrierIndex(candles)
    # Stop before a quote at the threshold boundary; missing intervals already
    # consumed the permitted gap. Never pause time for missing open-session bars.
    right=np.searchsorted(stamps,np.minimum(deadlines,censored_at),side='left')
    results=[]
    for i,entry in enumerate(candles):
        for side,d in (('long',1),('short',-1)):
            target=entry.open+d*Decimal('.0050');stop=entry.open-d*Decimal('.0020')
            if min(target,stop)<=0:raise ValueError('Nonpositive barriers')
            hit=tree.first_touch(i,int(right[i]),min(target,stop),max(target,stop))
            price=None
            if hit is None:
                end=min(int(deadlines[i]),int(censored_at[i]))
                if deadlines[i]<censored_at[i] or deadlines[i]==censored_at[i] and deadlines[i]==stamps[-1]+60:
                    outcome='timeout'
                    last=int(np.searchsorted(stamps,deadlines[i],side='left'))-1
                    price=candles[last].close
                else:outcome='censored'
            else:
                bar=candles[hit];end=int(stamps[hit])+60
                if d*(bar.open-stop)<=0 or d*(bar.open-target)>=0:
                    end=int(stamps[hit]);outcome='stop_loss' if d*(bar.open-stop)<=0 else 'take_profit'
                    price=bar.open if outcome=='stop_loss' else target
                else:
                    target_hit=bar.high>=target if d==1 else bar.low<=target
                    stop_hit=bar.low<=stop if d==1 else bar.high>=stop
                    if target_hit and stop_hit:outcome='ambiguous'
                    elif stop_hit:outcome='stop_loss';price=stop
                    else:outcome='take_profit' if end<deadlines[i] else 'boundary';price=target
            pnl=None if price is None else d*(price-entry.open)/Decimal('.0001')
            results.append(Trade(i,side,entry.timestamp,datetime.fromtimestamp(end,timezone.utc),entry.open,price,outcome,pnl))
    return results,deadlines


def session_events(candles, breaks, threshold):
    """CUSUM on observed closes; reset only at long gaps; next observed opening."""
    import math
    closes=np.asarray([float(c.close) for c in candles])
    events=np.zeros(len(candles),dtype=bool);positive=negative=0.0
    for i in range(1,len(candles)):
        if breaks[i]:positive=negative=0.0;continue
        change=math.log(closes[i])-math.log(closes[i-1])
        positive=max(0.0,positive+change);negative=min(0.0,negative+change)
        if negative < -threshold:events[i]=True;negative=0.0
        elif positive > threshold:events[i]=True;positive=0.0
    entries=np.zeros(len(candles),dtype=bool)
    entries[1:]=events[:-1]&~breaks[1:]
    return entries


def prepare_session(candles, protocol, spec, clock):
    begin,end=map(utc_epoch,protocol['development'])
    raw_stamps=np.asarray([int(c.timestamp.timestamp()) for c in candles],dtype=np.int64)
    if np.any((raw_stamps<begin)|(raw_stamps>=end)):raise ValueError('Reserved quotes rejected')
    active=clock.active[clock.indices(raw_stamps)]
    original_indices=np.flatnonzero(active)
    candles=[candles[i] for i in original_indices]
    stamps=raw_stamps[active]
    breaks=clock.gap_breaks(stamps,spec['censor_from_missing_minutes'])
    frame=session_features(candles,breaks)
    trades,deadlines=session_labels(candles,clock,spec['censor_from_missing_minutes'])
    entry=np.asarray([t.entry_index for t in trades],dtype=np.int64)
    side=np.asarray([1 if t.side=='long' else -1 for t in trades],dtype=np.int8)
    outcomes=np.asarray([t.outcome for t in trades])
    ends=np.asarray([int(t.end_time.timestamp()) for t in trades],dtype=np.int64)
    conclusive=np.isin(outcomes,['take_profit','stop_loss','timeout'])
    keep=conclusive&frame.valid[entry]
    rows=np.flatnonzero(keep);rows=rows[np.lexsort((side[rows],stamps[entry[rows]]))]
    selected=entry[rows];sides=side[rows]
    data=Dataset(orient_features(frame,selected,sides),(outcomes[rows]=='take_profit').astype(np.int8),
                 stamps[selected],ends[rows],deadlines[selected],original_indices[selected],sides,
                 frame.names,frame.groups,int((conclusive&~frame.valid[entry]).sum()))
    events={str(h):session_events(candles,breaks,h) for h in spec['thresholds']}
    masks={h:values[selected] for h,values in events.items()}
    observations=dict(starts=stamps[entry],outcomes=outcomes,valid=frame.valid[entry],
                      conclusive=conclusive,retained=keep,info_ends=deadlines[entry],
                      ends=ends,sides=side,entry_indices=original_indices[entry],
                      entry_price=np.asarray([float(t.entry_price) for t in trades]),
                      exit_price=np.asarray([float(t.exit_price) if t.exit_price is not None else np.nan for t in trades]),
                      pnl_pips=np.asarray([float(t.pnl_pips) if t.pnl_pips is not None else np.nan for t in trades]),
                      events={h:values[entry] for h,values in events.items()})
    stale=np.zeros(len(trades),dtype=np.int64)
    timed=np.flatnonzero(outcomes=='timeout')
    last=np.searchsorted(stamps,ends[timed],side='left')-1
    stale[timed]=clock.elapsed(stamps[last]+60,ends[timed])
    observations['timeout_stale_open_minutes']=stale
    diagnostics=dict(raw_observed_candles=len(raw_stamps),session_observed_candles=len(stamps),
                     excluded_outside_weekly_calendar=int((~active).sum()),long_gap_resets=int(breaks.sum()),
                     tolerated_short_gap_events=int(((clock.missing_open_minutes(stamps)>0)&
                       (clock.missing_open_minutes(stamps)<spec['censor_from_missing_minutes'])).sum()),
                     synthetic_candles=0,synthetic_entries=0,outcomes=dict(Counter(outcomes.tolist())))
    return data,masks,observations,diagnostics,stamps


def session_partitions(starts,info_ends,protocol,fold,clock,observed_stamps):
    starts,info_ends=np.asarray(starts),np.asarray(info_ends)
    if starts.shape!=info_ends.shape or not np.array_equal(info_ends,clock.deadlines(starts)):
        raise ValueError('Information ends must equal full session-clock horizons')
    begin,stop=map(utc_epoch,protocol['development'])
    if np.any((starts<begin)|(starts>=stop)):raise ValueError('Reserved entries rejected')
    inner,outer,end=(utc_epoch(fold[k]) for k in ('validation_start','test_start','test_end'))
    def cutoff(boundary):
        past=observed_stamps[observed_stamps<boundary]
        return int(past[-LOOKBACK]) if len(past)>=LOOKBACK else begin
    train=np.flatnonzero((starts<inner)&(info_ends<cutoff(inner)))
    refit=np.flatnonzero((starts<outer)&(info_ends<cutoff(outer)))
    validation=np.flatnonzero((starts>=inner)&(starts<outer)&(info_ends<outer))
    test=np.flatnonzero((starts>=outer)&(starts<end)&(info_ends<end))
    return dict(train=train,validation=validation,refit=refit,test=test)
