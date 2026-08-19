#!/usr/bin/env python3
"""Pilot nontrivial fully covariant projective Lagrangian observables.

For phase vectors phi_t = a_t-a_{t-1} in R^2, four nonzero projective
phase directions admit the GL(2)- and scale-invariant cross-ratio

  chi = [phi0,phi2][phi1,phi3] / ([phi0,phi3][phi1,phi2]),

where [u,v]=det(u,v). Every determinant picks up det(M) under a basis
change M, and each phi_i scale occurs once upstairs and downstairs, so chi
is invariant under GL(2) and independent nonzero rescaling of each phase.

We measure chi where nondegenerate, its variation along time, and the
projectively invariant degeneracy pattern where determinants vanish. No
preferred Euclidean metric is introduced.
"""
from __future__ import annotations
import argparse, json, math, random, statistics, sys
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src')); sys.path.insert(0,str(ROOT/'tools'))
import generate_targets as gt  # noqa:E402
import replicate_action_field_observables as base  # noqa:E402
from sugarscape import sugarscape as dtl  # noqa:E402

EPS=1e-10

def sub(a,b): return (float(a[0])-float(b[0]),float(a[1])-float(b[1]))
def det(a,b): return float(a[0])*float(b[1])-float(a[1])*float(b[0])
def zero(a): return abs(a[0])<=EPS and abs(a[1])<=EPS

def cross_ratio(p0,p1,p2,p3):
    """Return (kind, value). kind records projective degeneracy covariantly."""
    ps=(p0,p1,p2,p3)
    if any(zero(p) for p in ps): return ('zero_phase',None)
    d02,d13,d03,d12=det(p0,p2),det(p1,p3),det(p0,p3),det(p1,p2)
    mask=(abs(d02)<=EPS,abs(d13)<=EPS,abs(d03)<=EPS,abs(d12)<=EPS)
    if any(mask): return ('degenerate:'+''.join('1' if x else '0' for x in mask),None)
    return ('regular',(d02*d13)/(d03*d12))

def transform(v,M): return (M[0][0]*v[0]+M[0][1]*v[1],M[1][0]*v[0]+M[1][1]*v[1])

def sequence_metrics(actions,check=False):
    phases=[sub(actions[i],actions[i-1]) for i in range(1,len(actions))]
    kinds=Counter(); logs=[]; signed=[]; variation=[]; prev=None; regular=0; total=max(0,len(phases)-3)
    for i in range(3,len(phases)):
        ps=(phases[i],phases[i-1],phases[i-2],phases[i-3]); kind,chi=cross_ratio(*ps); kinds[kind]+=1
        if kind=='regular' and chi is not None and abs(chi)>EPS and math.isfinite(chi):
            regular+=1; lv=math.log(abs(chi)); logs.append(lv); signed.append(1 if chi>0 else -1)
            if prev is not None: variation.append(abs(lv-prev))
            prev=lv
        else: prev=None
        if check and kind=='regular':
            # Exact projective covariance checks on representative integer GL(2) maps
            for M in (((0,1),(1,0)),((1,1),(0,1)),((-1,0),(0,1)),((2,1),(1,1))):
                kind2,chi2=cross_ratio(*(transform(p,M) for p in ps))
                if kind2!='regular' or not math.isclose(chi,chi2,rel_tol=1e-9,abs_tol=1e-9): raise AssertionError(('GL2',chi,chi2,M,ps))
            scales=(2.0,3.0,5.0,7.0)
            kind3,chi3=cross_ratio(*(tuple(scales[j]*x for x in ps[j]) for j in range(4)))
            if kind3!='regular' or not math.isclose(chi,chi3,rel_tol=1e-9,abs_tol=1e-9): raise AssertionError(('scale',chi,chi3,ps))
    def med(xs): return statistics.median(xs) if xs else None
    return {'windows':total,'regular_windows':regular,'regular_fraction':regular/max(1,total),
            'degeneracy':dict(kinds),'median_logabs_chi':med(logs),'mean_abs_logabs_chi':statistics.fmean(abs(x) for x in logs) if logs else None,
            'median_abs_delta_logabs_chi':med(variation),'mean_abs_delta_logabs_chi':statistics.fmean(variation) if variation else None,
            'positive_chi_fraction':sum(1 for x in signed if x>0)/len(signed) if signed else None}

def merge_metrics(metrics):
    windows=sum(m['windows'] for m in metrics); regular=sum(m['regular_windows'] for m in metrics); deg=Counter();
    for m in metrics: deg.update(m['degeneracy'])
    # Run-level means are deliberate: keep agents/runs from being swamped by long-lived trajectories.
    keys=('regular_fraction','median_logabs_chi','mean_abs_logabs_chi','median_abs_delta_logabs_chi','mean_abs_delta_logabs_chi','positive_chi_fraction')
    out={'windows':windows,'regular_windows':regular,'regular_fraction_weighted':regular/max(1,windows),'degeneracy':dict(deg)}
    for k in keys:
        vals=[m[k] for m in metrics if m[k] is not None]; out[k+'_mean']=statistics.fmean(vals) if vals else None
    return out

def target_mean(sim,spec):
    pop=len(sim.agents)
    if spec.variable=='population': return float(pop)
    if spec.variable=='wealth': return float(sim.runtimeStats.get('giniCoefficient',0.0))
    if spec.variable=='mean_trade_price': return float(sim.runtimeStats.get('meanTradePrice',0.0))
    if spec.variable=='majority_tribe_share': return Counter(a.tribe for a in sim.agents).most_common(1)[0][1]/pop if pop else 0.0
    return 0.0

def run_one(si,seed):
    spec=gt.SPECS[si]; cfg=gt.build_run_config(spec,seed); random.seed(seed); base.install_hooks(); sim=dtl.Sugarscape(cfg); sim.updateRuntimeStats(); base.ACTIVE_SIM=sim
    seq=defaultdict(list); window=[]; T=int(cfg['timesteps']); w0=T-gt.WINDOW_TICKS
    for tick in range(1,T+1):
        if not sim.agents: break
        tr=base.TickTracker(sim,tick); base.ACTIVE_TRACKER=tr; sim.doTimestep(); base.ACTIVE_TRACKER=None
        for aid,a in tr.actions.items(): seq[int(aid)].append(tuple(map(int,a)))
        if tick>w0: window.append(target_mean(sim,spec))
    base.ACTIVE_SIM=None
    actual=[]; shuffled=[]; rng=random.Random(20_000_000+si*1000+seed); checked=False
    for actions in seq.values():
        if len(actions)<5: continue
        actual.append(sequence_metrics(actions,check=not checked)); checked=True
        sh=list(actions); rng.shuffle(sh); shuffled.append(sequence_metrics(sh))
    A=merge_metrics(actual); S=merge_metrics(shuffled)
    ratios={}
    for k in ('regular_fraction_weighted','mean_abs_logabs_chi_mean','mean_abs_delta_logabs_chi_mean'):
        if A.get(k) is not None and S.get(k) not in (None,0): ratios[k+'_ratio_to_shuffle']=A[k]/S[k]
    return {'spec':spec.target_id,'seed':seed,'final_gini':float(sim.runtimeStats.get('giniCoefficient',0.0)),'final_population':len(sim.agents),'target_window_mean':statistics.fmean(window) if window else None,
            'projective':A,'shuffled':S,'ratios':ratios,'covariance_checked':checked}

def mean(rows,path,key):
    vals=[r[path].get(key) for r in rows if r[path].get(key) is not None]; return statistics.fmean(vals) if vals else None

def summarize(runs):
    by={}
    for spec in [s.target_id for s in gt.SPECS]:
        rr=[r for r in runs if r['spec']==spec]
        by[spec]={'runs':len(rr),'projective':{k:mean(rr,'projective',k) for k in ('regular_fraction_weighted','median_logabs_chi_mean','mean_abs_logabs_chi_mean','median_abs_delta_logabs_chi_mean','mean_abs_delta_logabs_chi_mean','positive_chi_fraction_mean')},
                  'shuffled':{k:mean(rr,'shuffled',k) for k in ('regular_fraction_weighted','median_logabs_chi_mean','mean_abs_logabs_chi_mean','median_abs_delta_logabs_chi_mean','mean_abs_delta_logabs_chi_mean','positive_chi_fraction_mean')},
                  'ratios':{k:mean(rr,'ratios',k) for k in set().union(*(r['ratios'].keys() for r in rr))},'covariance_all':all(r['covariance_checked'] for r in rr)}
    return {'schema':'sugarscape.projective-lagrangian.pilot.v1','definition':'chi=[phi0,phi2][phi1,phi3]/([phi0,phi3][phi1,phi2])','by_replication':by,'runs':runs}

def main():
    p=argparse.ArgumentParser(); p.add_argument('--seeds',type=int,default=3); p.add_argument('--jobs',type=int,default=6); p.add_argument('--output',type=Path,default=Path('build/projective-lagrangian-pilot.json')); a=p.parse_args(); runs=[]
    with ProcessPoolExecutor(max_workers=a.jobs) as pool:
        fs=[pool.submit(run_one,si,seed) for si in range(len(gt.SPECS)) for seed in range(1,a.seeds+1)]
        for n,f in enumerate(as_completed(fs),1): r=f.result(); runs.append(r); print(n,len(fs),r['spec'],r['seed'],flush=True)
    runs.sort(key=lambda r:([s.target_id for s in gt.SPECS].index(r['spec']),r['seed'])); out=summarize(runs); a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps(out,indent=2,sort_keys=True)+'\n')
if __name__=='__main__': main()
