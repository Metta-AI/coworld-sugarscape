#!/usr/bin/env python3
"""Measure candidate covariant discrete Lagrangians on canonical Sugarscape replications.

Primary metric-free candidates, for an agent action a_t in R^2:
  phi_t   = a_t - a_{t-1}
  sigma_t = phi_t - phi_{t-1}

  K_strict(t) = sum_i 1[sigma_i(t) != 0]
  K_proj(t)   = sum_i 1[[phi_i(t)] != [phi_i(t-1)]]

where [v] is the oriented positive ray, with zero retained as its own state.
Both are invariant under any fixed invertible linear change of the spatial basis.
K_proj is additionally invariant under positive rescaling of each compared phase vector.

For the four-channel field F_t=(x+,x-,y+,y-), the exact same definitions are used.
The primitive event basis and the Q/M basis are checked explicitly for equality.

The study also computes temporally shuffled nulls that preserve each agent's action
multiset but destroy ordering. This asks whether realized paths carry fewer defects
than expected from their one-step action statistics alone.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
import json, math, random, statistics, sys
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src')); sys.path.insert(0,str(ROOT/'tools'))
import generate_targets as gt  # noqa: E402
import replicate_action_field_observables as base  # noqa: E402
from sugarscape import sugarscape as dtl  # noqa: E402

EPS=1e-9


def vec_sub(a,b): return tuple(float(x)-float(y) for x,y in zip(a,b))
def vec_zero(v): return all(abs(float(x))<=EPS for x in v)
def vec_equal(a,b): return all(abs(float(x)-float(y))<=EPS for x,y in zip(a,b))

def same_positive_ray(a,b):
    """Positive projective equality without choosing a norm or angle."""
    za,zb=vec_zero(a),vec_zero(b)
    if za or zb: return za and zb
    pivot=next(i for i,x in enumerate(b) if abs(float(x))>EPS)
    lam=float(a[pivot])/float(b[pivot])
    if lam<=0: return False
    scale=max(1.0,max(abs(float(x)) for x in a),abs(lam)*max(abs(float(x)) for x in b))
    return all(abs(float(x)-lam*float(y))<=EPS*scale for x,y in zip(a,b))

def phase(action_now,action_prev): return vec_sub(action_now,action_prev)
def shift(a0,a1,a2): return vec_sub(phase(a0,a1),phase(a1,a2))

def action_sequence_metrics(actions):
    """Sequence-only candidate actions; no environment or hidden state."""
    strict=proj_phase=proj_action=proj_shift=0
    channel=0; l1=0.0; sq=0.0; opp=0; span_rank=Counter()
    if len(actions)<4:
        return {k:0.0 for k in ('strict','projective_phase','projective_action','projective_shift','channel','shift_l1','shift_sq','opportunities')}
    prev_sigma=None
    for t in range(2,len(actions)):
        a0,a1,a2=actions[t],actions[t-1],actions[t-2]
        p0,p1=phase(a0,a1),phase(a1,a2); s=vec_sub(p0,p1)
        opp+=1
        strict += int(not vec_zero(s))
        proj_phase += int(not same_positive_ray(p0,p1))
        proj_action += int(not same_positive_ray(a0,a1))
        channel += sum(abs(x)>EPS for x in s)
        l1 += sum(abs(float(x)) for x in s); sq += sum(float(x)*float(x) for x in s)
        if prev_sigma is not None: proj_shift += int(not same_positive_ray(s,prev_sigma))
        prev_sigma=s
    return {'strict':strict,'projective_phase':proj_phase,'projective_action':proj_action,
            'projective_shift':proj_shift,'channel':channel,'shift_l1':l1,'shift_sq':sq,'opportunities':opp}

def q_m_basis(f):
    xp,xm,yp,ym=map(float,f)
    return (xp-xm,xp+xm,yp-ym,yp+ym)

def field_sequence_metrics(fields):
    strict=proj_phase=proj_action=proj_shift=0; l1=sq=0.0; opp=0; prev_sigma=None
    if len(fields)<3: return {'strict':0,'projective_phase':0,'projective_action':0,'projective_shift':0,'shift_l1':0.0,'shift_sq':0.0,'opportunities':0}
    for t in range(2,len(fields)):
        f0,f1,f2=fields[t],fields[t-1],fields[t-2]
        p0,p1=phase(f0,f1),phase(f1,f2); s=vec_sub(p0,p1); opp+=1
        strict+=int(not vec_zero(s)); proj_phase+=int(not same_positive_ray(p0,p1)); proj_action+=int(not same_positive_ray(f0,f1))
        l1+=sum(abs(x) for x in s); sq+=sum(x*x for x in s)
        if prev_sigma is not None: proj_shift+=int(not same_positive_ray(s,prev_sigma))
        prev_sigma=s
    return {'strict':strict,'projective_phase':proj_phase,'projective_action':proj_action,'projective_shift':proj_shift,'shift_l1':l1,'shift_sq':sq,'opportunities':opp}

def stock_sugar(sim):
    return sum(max(0.0,float(c.sugar)) for col in sim.environment.grid for c in col)+sum(max(0.0,float(a.sugar)) for a in sim.agents if a.isAlive())

def target_sample(sim,spec):
    pop=len(sim.agents)
    if spec.variable=='population': return [float(pop)]
    if spec.variable=='wealth': return [float(a.sugar+a.spice) for a in sim.agents]
    if spec.variable=='majority_tribe_share':
        return [Counter(a.tribe for a in sim.agents).most_common(1)[0][1]/pop] if pop else []
    if spec.variable=='mean_trade_price': return [float(sim.runtimeStats.get('meanTradePrice',0.0))]
    return []

def run_one(spec_index,seed):
    global_fields=[]
    spec=gt.SPECS[spec_index]; config=gt.build_run_config(spec,seed); random.seed(seed)
    base.install_hooks(); sim=dtl.Sugarscape(config); sim.updateRuntimeStats(); base.ACTIVE_SIM=sim
    seq=defaultdict(list); target_samples=[]; tick_rows=[]; reconciliation_abs=0.0; reconciliation_gross=0.0
    timesteps=int(config['timesteps']); window_start=timesteps-gt.WINDOW_TICKS
    for tick in range(1,timesteps+1):
        if not sim.agents: break
        stock0=stock_sugar(sim); tr=base.TickTracker(sim,tick); base.ACTIVE_TRACKER=tr; sim.doTimestep(); base.ACTIVE_TRACKER=None; stock1=stock_sugar(sim)
        # Runtime stats survive even though DTL clears the lifecycle object lists.
        yplus=float(sim.runtimeStats.get('agentsBorn',0))+float(sim.runtimeStats.get('agentsReplaced',0)); yminus=float(sim.runtimeStats.get('agentDeaths',0))
        xp=sum(float(v) for v in tr.sugar_create.values()); xm=sum(float(v) for v in tr.sugar_annihilate.values())
        residual=(stock1-stock0)-(xp-xm)
        reconciliation_abs+=abs(residual); reconciliation_gross+=xp+xm
        if residual>EPS: xp+=residual
        elif residual<-EPS: xm+=-residual
        field=(xp,xm,yplus,yminus); global_fields.append(field)
        for aid,a in tr.actions.items(): seq[int(aid)].append(tuple(map(int,a)))
        if tick>window_start:
            target_samples.extend(target_sample(sim,spec))
            defects=channels=proj_phase=proj_action=proj_shift=0; l1=sq=0.0; resolved=0
            for actions in seq.values():
                if len(actions)<3: continue
                resolved+=1; a0,a1,a2=actions[-1],actions[-2],actions[-3]; p0,p1=phase(a0,a1),phase(a1,a2); s=vec_sub(p0,p1)
                defects+=int(not vec_zero(s)); proj_phase+=int(not same_positive_ray(p0,p1)); proj_action+=int(not same_positive_ray(a0,a1)); channels+=sum(abs(x)>EPS for x in s); l1+=sum(abs(x) for x in s); sq+=sum(x*x for x in s)
                if len(actions)>=4:
                    sprev=shift(actions[-2],actions[-3],actions[-4]); proj_shift+=int(not same_positive_ray(s,sprev))
            fm=field_sequence_metrics(global_fields[-4:]) if len(global_fields)>=3 else {'strict':0,'projective_phase':0,'projective_action':0,'projective_shift':0,'shift_l1':0.0,'shift_sq':0.0,'opportunities':0}
            tick_rows.append({'tick':tick,'resolved_agents':resolved,'K_agent_strict':defects,'K_agent_projective_phase':proj_phase,'K_agent_projective_action':proj_action,'K_agent_projective_shift':proj_shift,
                              'K_agent_channel':channels,'K_agent_shift_l1':l1,'K_agent_shift_sq':sq,'K_field_strict':fm['strict'],'K_field_projective_phase':fm['projective_phase'],
                              'K_field_projective_action':fm['projective_action'],'K_field_projective_shift':fm['projective_shift'],'K_field_shift_l1':fm['shift_l1'],'K_total_strict':defects+fm['strict'],
                              'K_total_projective_phase':proj_phase+fm['projective_phase']})
    base.ACTIVE_SIM=None
    # Sequence totals over all mature action histories.
    actual=Counter(); shuffled=Counter(); reversed_=Counter(); swapped=Counter(); signflip=Counter()
    rng=random.Random(10_000_000+spec_index*1000+seed)
    for aid,actions in seq.items():
        m=action_sequence_metrics(actions)
        for k,v in m.items(): actual[k]+=v
        sh=list(actions); rng.shuffle(sh)
        for k,v in action_sequence_metrics(sh).items(): shuffled[k]+=v
        for k,v in action_sequence_metrics(list(reversed(actions))).items(): reversed_[k]+=v
        for k,v in action_sequence_metrics([(y,x) for x,y in actions]).items(): swapped[k]+=v
        for k,v in action_sequence_metrics([(-x,-y) for x,y in actions]).items(): signflip[k]+=v
    field_actual=field_sequence_metrics(global_fields); field_qm=field_sequence_metrics([q_m_basis(f) for f in global_fields])
    # Exact covariance checks for metric-free terms.
    for key in ('strict','projective_phase','projective_action','projective_shift'):
        if actual[key]!=swapped[key] or actual[key]!=signflip[key]: raise AssertionError(('agent covariance',key,actual[key],swapped[key],signflip[key]))
        if field_actual[key]!=field_qm[key]: raise AssertionError(('field basis covariance',key,field_actual[key],field_qm[key]))
    opp=max(1,float(actual['opportunities'])); fopp=max(1,float(field_actual['opportunities']))
    def dens(c,key): return float(c[key])/max(1.0,float(c['opportunities']))
    strict_series=[r['K_agent_strict']/max(1,r['resolved_agents']) for r in tick_rows]
    proj_series=[r['K_agent_projective_phase']/max(1,r['resolved_agents']) for r in tick_rows]
    return {'spec':spec.target_id,'seed':seed,'completed_ticks':int(sim.timestep),'final_population':len(sim.agents),'final_gini':float(sim.runtimeStats.get('giniCoefficient',0.0)),
            'target_window_mean':statistics.fmean(target_samples) if target_samples else None,
            'lagrangian':{
                'agent_strict_density':dens(actual,'strict'),'agent_projective_phase_density':dens(actual,'projective_phase'),'agent_projective_action_density':dens(actual,'projective_action'),
                'agent_projective_shift_density':dens(actual,'projective_shift'),'agent_channel_density':dens(actual,'channel'),'agent_shift_l1_density':dens(actual,'shift_l1'),'agent_shift_sq_density':dens(actual,'shift_sq'),
                'field_strict_density':dens(field_actual,'strict'),'field_projective_phase_density':dens(field_actual,'projective_phase'),'field_projective_action_density':dens(field_actual,'projective_action'),
                'field_projective_shift_density':dens(field_actual,'projective_shift'),'field_shift_l1_density':dens(field_actual,'shift_l1'),
                'total_strict_action':float(actual['strict']+field_actual['strict']),'total_projective_phase_action':float(actual['projective_phase']+field_actual['projective_phase']),
                'agent_opportunities':int(actual['opportunities']),'field_opportunities':int(field_actual['opportunities'])},
            'null':{
                'shuffled_strict_density':dens(shuffled,'strict'),'shuffled_projective_phase_density':dens(shuffled,'projective_phase'),'shuffled_projective_action_density':dens(shuffled,'projective_action'),
                'strict_ratio_to_shuffle':dens(actual,'strict')/max(EPS,dens(shuffled,'strict')),'projective_phase_ratio_to_shuffle':dens(actual,'projective_phase')/max(EPS,dens(shuffled,'projective_phase')),
                'projective_action_ratio_to_shuffle':dens(actual,'projective_action')/max(EPS,dens(shuffled,'projective_action'))},
            'covariance':{
                'axis_swap_exact':all(actual[k]==swapped[k] for k in ('strict','projective_phase','projective_action','projective_shift')),
                'global_sign_exact':all(actual[k]==signflip[k] for k in ('strict','projective_phase','projective_action','projective_shift')),
                'field_QM_basis_exact':all(field_actual[k]==field_qm[k] for k in ('strict','projective_phase','projective_action','projective_shift')),
                'time_reverse_strict_delta':float(reversed_['strict']-actual['strict']),'time_reverse_projective_phase_delta':float(reversed_['projective_phase']-actual['projective_phase'])},
            'field_accounting':{'reconciliation_abs':reconciliation_abs,'raw_gross':reconciliation_gross,'reconciliation_fraction_of_raw_gross':reconciliation_abs/max(EPS,reconciliation_gross)},
            'tick_summary':{'strict_mean':statistics.fmean(strict_series) if strict_series else None,'strict_sd':statistics.pstdev(strict_series) if len(strict_series)>1 else 0.0,
                            'projective_phase_mean':statistics.fmean(proj_series) if proj_series else None,'projective_phase_sd':statistics.pstdev(proj_series) if len(proj_series)>1 else 0.0}}


def corr(xs,ys):
    pairs=[(float(x),float(y)) for x,y in zip(xs,ys) if x is not None and y is not None and math.isfinite(float(x)) and math.isfinite(float(y))]
    if len(pairs)<4:return None
    a,b=zip(*pairs); ma,mb=statistics.fmean(a),statistics.fmean(b); da=[x-ma for x in a]; db=[y-mb for y in b]; va=sum(x*x for x in da); vb=sum(y*y for y in db)
    return sum(x*y for x,y in zip(da,db))/math.sqrt(va*vb) if va>EPS and vb>EPS else None

def mean(rows,key,path='lagrangian'):
    vals=[float(r[path][key]) for r in rows if r[path].get(key) is not None]; return statistics.fmean(vals) if vals else None

def summarize(runs):
    by={}
    for spec in [s.target_id for s in gt.SPECS]:
        rr=[r for r in runs if r['spec']==spec]
        metrics={k:mean(rr,k) for k in rr[0]['lagrangian'] if isinstance(rr[0]['lagrangian'][k],(int,float))}
        nulls={k:mean(rr,k,'null') for k in rr[0]['null']}
        by[spec]={'runs':len(rr),'lagrangian_mean':metrics,'null_mean':nulls,
                  'outcome_correlations':{k:{'final_gini':corr([r['lagrangian'][k] for r in rr],[r['final_gini'] for r in rr]),
                                              'final_population':corr([r['lagrangian'][k] for r in rr],[r['final_population'] for r in rr]),
                                              'target_window_mean':corr([r['lagrangian'][k] for r in rr],[r['target_window_mean'] for r in rr])}
                                          for k in ('agent_strict_density','agent_projective_phase_density','agent_projective_shift_density','field_strict_density','total_strict_action')},
                  'covariance_checks':{'axis_swap_all':all(r['covariance']['axis_swap_exact'] for r in rr),'global_sign_all':all(r['covariance']['global_sign_exact'] for r in rr),'field_QM_all':all(r['covariance']['field_QM_basis_exact'] for r in rr),
                                       'max_abs_time_reverse_strict_delta':max(abs(r['covariance']['time_reverse_strict_delta']) for r in rr),
                                       'max_abs_time_reverse_projective_phase_delta':max(abs(r['covariance']['time_reverse_projective_phase_delta']) for r in rr)},
                  'field_reconciliation_fraction_mean':statistics.fmean(r['field_accounting']['reconciliation_fraction_of_raw_gross'] for r in rr)}
    return {'schema':'sugarscape.discrete-lagrangian.replication.v1','base_commit':'7b610e077a2e6cfa74cb938423dff9e7edc26107','definitions':{
                'agent_strict':'sum_i 1[Delta^2 a_i(t) != 0]','agent_projective_phase':'sum_i 1[[Delta a_i(t)] != [Delta a_i(t-1)]]','field_strict':'1[Delta^2 F(t) != 0]','field_projective_phase':'1[[Delta F(t)] != [Delta F(t-1)]]'},
            'by_replication':by,'runs':runs}

def main():
    p=argparse.ArgumentParser(); p.add_argument('--seeds',type=int,default=30); p.add_argument('--jobs',type=int,default=6); p.add_argument('--output',type=Path,default=Path('build/discrete-lagrangian-study.json')); a=p.parse_args()
    jobs=[]; runs=[]
    with ProcessPoolExecutor(max_workers=a.jobs) as pool:
        for si in range(len(gt.SPECS)):
            for seed in range(1,a.seeds+1): jobs.append(pool.submit(run_one,si,seed))
        for n,f in enumerate(as_completed(jobs),1):
            r=f.result(); runs.append(r); print(f"{n}/{len(jobs)} {r['spec']} seed {r['seed']}",flush=True)
    runs.sort(key=lambda r:([s.target_id for s in gt.SPECS].index(r['spec']),r['seed']))
    out=summarize(runs); a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps(out,indent=2,sort_keys=True)+'\n'); print(a.output)

if __name__=='__main__': main()
