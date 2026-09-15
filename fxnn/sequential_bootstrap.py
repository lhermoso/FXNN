"""Bounded interval bootstrap; candidate probabilities use no labels or features."""
import hashlib
import json
import numpy as np

EPS = np.finfo(np.float64).eps
ATOL, RTOL = 1e-14, 1e-12


def gamma(n):
    value = n*EPS
    if not 0 <= value < .5:
        raise ValueError('Unrepresentable floating error budget')
    return np.nextafter(value/(1-value), np.inf)


def canonical_order(ids):
    ids = np.asarray(ids)
    if ids.ndim != 1 or not np.issubdtype(ids.dtype, np.integer) or len(np.unique(ids)) != len(ids):
        raise ValueError('Original entry identities must be unique integers')
    order = np.argsort(ids, kind='stable')
    inverse = np.empty(len(ids), dtype=np.int64); inverse[order] = np.arange(len(ids))
    return order, inverse


def seed_for(training_hash, population, master, member):
    material = dict(experiment='sequential_bagging_v1',task='dynamic',population=population,
                    master_seed=master,member=member,training_sampling_contract_sha256=training_hash)
    return int.from_bytes(hashlib.sha256(json.dumps(material,sort_keys=True).encode()).digest()[:16], 'big')


class IntervalIndex:
    def __init__(self, starts, ends):
        starts, ends = np.asarray(starts), np.asarray(ends)
        if (starts.ndim != 1 or starts.shape != ends.shape or not len(starts)
                or not np.issubdtype(starts.dtype,np.integer) or not np.issubdtype(ends.dtype,np.integer)
                or np.any(ends <= starts)):
            raise ValueError('Positive integer event intervals required')
        if int(ends.max())-int(starts.min()) > np.iinfo(np.int64).max:
            raise ValueError('Integer coordinate differences would overflow')
        origin = int(starts.min())
        starts = np.fromiter((int(v)-origin for v in starts),dtype=np.int64,count=len(starts))
        ends = np.fromiter((int(v)-origin for v in ends),dtype=np.int64,count=len(ends))
        bounds = np.unique(np.concatenate((starts,ends)))
        self.d = np.diff(bounds).astype(np.float64)
        self.L, self.R = np.searchsorted(bounds,starts), np.searchsorted(bounds,ends)
        self.D = (ends-starts).astype(np.float64)
        self.c = np.zeros(len(self.d),dtype=np.int64)
        self.height = (len(self.d)-1).bit_length()
        self.size = 1 << self.height
        self.draw_count = 0

    def add(self, event):
        self.c[self.L[event]:self.R[event]] += 1
        self.draw_count += 1

    def _tree_queries(self, terms, selected):
        tree = np.zeros(2*self.size)
        tree[self.size:self.size+len(terms)] = terms
        width = self.size//2
        while width:
            tree[width:2*width] = tree[2*width:4*width:2]+tree[2*width+1:4*width:2]
            width //= 2
        left,right = self.L[selected]+self.size,self.R[selected]+self.size
        total = np.zeros(len(selected)); contributions = np.zeros(len(selected),dtype=np.int64)
        levels = 0
        while np.any(left < right):
            if levels > self.height:
                raise ValueError('Range tree exceeded bounded query levels')
            active = left < right
            take = active & ((left & 1) == 1)
            total[take] += tree[left[take]]; contributions[take] += 1; left[take] += 1
            take = active & ((right & 1) == 1)
            right[take] -= 1; total[take] += tree[right[take]]; contributions[take] += 1
            left //= 2; right //= 2; levels += 1
        if np.any(contributions > 2*self.height+2):
            raise ValueError('Range tree exceeded bounded node contributions')
        return total/self.D[selected], levels

    def uniqueness(self, prospective=True):
        denom = self.c+1 if prospective else np.maximum(self.c,1)
        terms = self.d/denom
        if not prospective:
            terms[self.c == 0] = 0
        if not np.isfinite(terms).all() or np.any((terms > 0) & (terms < np.finfo(float).tiny)):
            raise ValueError('Invalid range-sum intermediate')
        prefix = np.concatenate(([0.],np.cumsum(terms)))
        g = gamma(len(terms)+3)
        B = np.nextafter(g*(terms.sum()/(1-g)),np.inf)
        values = (prefix[self.R]-prefix[self.L])/self.D
        error = np.nextafter((2*B+EPS*(abs(prefix[self.R])+abs(prefix[self.L])))/self.D+gamma(2)*abs(values),np.inf)
        tolerance = ATOL+RTOL*np.maximum(abs(values)-error,0)
        suspect = (error > tolerance) | ~np.isfinite(values)
        levels = 0
        if suspect.any():
            selected = np.flatnonzero(suspect)
            values[selected], levels = self._tree_queries(terms,selected)
            gtree = gamma(3*self.height+8)
            error[selected] = np.nextafter(gtree/(1-gtree)*abs(values[selected]),np.inf)
        if (not np.isfinite(values).all() or not np.isfinite(error).all()
                or np.any(error > ATOL+RTOL*np.maximum(abs(values)-error,0))):
            raise ValueError('Interval sum exceeded numerical error budget')
        lower = 1/(self.draw_count+1) if prospective else 0
        if np.any(values < lower-ATOL-RTOL) or np.any(values > 1+ATOL+RTOL):
            raise ValueError('Uniqueness outside mathematical bounds')
        return values, dict(errors=error,tree_queries=int(suspect.sum()),max_levels=levels)

    def probabilities(self):
        u, info = self.uniqueness()
        p = u/u.sum()
        if not np.isfinite(p).all() or np.any(p <= 0) or abs(p.sum()-1) > 1e-12:
            raise ValueError('Invalid sampling probabilities')
        return p, info

    def diagnostics(self, draws):
        u, _ = self.uniqueness(prospective=False)
        identities, multiplicity = np.unique(draws,return_counts=True)
        active = self.c > 0
        return dict(raw_mean_uniqueness=float(u[draws].mean()),
                    raw_uniqueness_min=float(u[draws].min()),raw_uniqueness_max=float(u[draws].max()),
                    distinct_ids=len(multiplicity),repetitions=len(draws)-len(multiplicity),
                    multiplicities=multiplicity.tolist(),distinct_event_indices=identities.tolist(),
                    raw_uniqueness=u[draws].tolist(),coverage_open_minutes=float(self.d[active].sum()),
                    max_concurrency=int(self.c.max()),
                    mean_active_concurrency=float(np.average(self.c[active],weights=self.d[active])),
                    effective_sample_size_claim=False)


def sample(starts, ends, uniforms, scheme, callback=None):
    uniforms = np.asarray(uniforms)
    if uniforms.ndim != 1 or not len(uniforms) or not np.isfinite(uniforms).all() or np.any((uniforms < 0)|(uniforms >= 1)):
        raise ValueError('Fixed uniforms must be finite in [0,1)')
    if scheme not in ('uniform','sequential'):
        raise ValueError('Unregistered sampling scheme')
    index = IntervalIndex(starts,ends)
    draws = np.empty(len(uniforms),dtype=np.int64); chosen = np.empty(len(uniforms))
    queries,levels = 0,0
    for step,u in enumerate(uniforms):
        if scheme == 'sequential':
            p, info = index.probabilities()
            queries += info['tree_queries']; levels = max(levels,info['max_levels'])
        else:
            p = np.full(len(starts),1/len(starts))
        if callback is not None: callback(step,p)
        cdf = np.cumsum(p); cdf[-1] = 1.
        event = int(np.searchsorted(cdf,u,side='right'))
        draws[step],chosen[step] = event,p[event]
        index.add(event)
    return dict(draws=draws,chosen_probabilities=chosen,uniforms=uniforms.copy(),
                diagnostics=index.diagnostics(draws),tree_queries=queries,max_query_levels=levels)
