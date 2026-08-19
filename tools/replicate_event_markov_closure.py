#!/usr/bin/env python3
from __future__ import annotations

import argparse, json, math, random, statistics, sys
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src')); sys.path.insert(0,str(ROOT/'tools'))
import generate_targets as gt  # noqa: E402
import replicate_action_field_observables as base  # noqa: E402
from sugarscape import sugarscape as dtl  # noqa: E402

HEADINGS=('0','+1','inf','-1')
HIDX={h:i for i,h in enumerate(HEADINGS)}
REST='rest'
ALPHA=0.5


def heading(v):
    x,y=v
    if x==0 and y==0:return REST
    if y==0:return '0'
    if x==0:return 'inf'
    return '+1' if x*y>0 else '-1'

def pure_reversal(a,b):
    if a==(0,0) or b==(0,0):return False
    ax,ay=a; bx,by=b
    return ax*by-ay*bx==0 and ax*bx+ay*by<0

def winding_step(a,b):
    ha,hb=heading(a),heading(b)
    if ha==REST or hb==REST or ha==hb:return 0
    ia,ib=HIDX[ha],HIDX[hb]; d=(ib-ia)%4
    if d==1:return 1
    if d==3:return -1
    cross=a[0]*b[1]-a[1]*b[0]
    if cross>0:return 2
    if cross<0:return -2
    return 0

def event_kind(a,b):
    if heading(a)==REST or heading(b)==REST:return 'rest-transition'
    if pure_reversal(a,b):return 'reversal'
    if heading(a)!=heading(b):return 'turn'
    return 'speed-only'

def m_orders(actions_by_id,living_ids):
    if not living_ids:return (0.0,0.0)
    z1=z2=0j
    for aid in living_ids:
        v=actions_by_id.get(aid,(0,0)); x,y=v
        if x==0 and y==0:continue
        th=math.atan2(y,x); z1+=complex(math.cos(th),math.sin(th)); z2+=complex(math.cos(2*th),math.sin(2*th))
    n=len(living_ids)
    return (abs(z1/n),abs(z2/n))

def q01(x,bins=20):return max(0,min(bins-1,int(float(x)*bins)))
def slog(x):
    x=int(round(x))
    if x==0:return 0
    return (1 if x>0 else -1)*(1+int(math.log2(abs(x))))
def pairwise_hist(ws):
    c=Counter(ws); vals=sorted(c); out=Counter()
    for i,a in enumerate(vals):
        na=c[a]
        out[0]+=na*(na-1)//2
        for b in vals[i+1:]:out[b-a]+=na*c[b]
    return tuple(sorted((int(k),int(v)) for k,v in out.items() if v))
def pair_summary(hist):
    total=sum(n for _,n in hist)
    if not total:return (0,0,0,0)
    mean=sum(abs(d)*n for d,n in hist)/total
    odd=sum(n for d,n in hist if abs(d)%2)/total
    mx=max((abs(d) for d,_ in hist),default=0)
    ent=0.0
    for _,n in hist:
        p=n/total; ent-=p*math.log2(p)
    return (slog(mean),q01(min(1.0,odd)),slog(mx),q01(min(1.0,ent/8)))

class Model:
    def __init__(self):
        self.ctx=defaultdict(Counter); self.base=Counter()
    def add(self,c,y):self.ctx[c][y]+=1; self.base[y]+=1
    def prob(self,c,y):
        vocab=max(1,len(self.base)); cc=self.ctx.get(c); n=sum(cc.values()) if cc else 0
        # backoff-smoothed with empirical base prior
        bn=sum(self.base.values()); prior=(self.base[y]+ALPHA)/(bn+ALPHA*vocab)
        if not cc:return prior
        return (cc[y]+ALPHA*prior)/(n+ALPHA)

def score(train_records,test_records,state_key,target_key):
    m1,m2=Model(),Model(); seen1=set(); seen2=set()
    for rec in train_records:
        s=rec[state_key]; p=rec.get(state_key+'_prev'); y=rec[target_key]
        m1.add(s,y); seen1.add(s)
        if p is not None:m2.add((p,s),y); seen2.add((p,s))
    l1=l2=0.0; n=0; cov1=cov2=0
    for rec in test_records:
        s=rec[state_key]; p=rec.get(state_key+'_prev'); y=rec[target_key]
        if p is None:continue
        l1-=math.log2(max(1e-300,m1.prob(s,y))); l2-=math.log2(max(1e-300,m2.prob((p,s),y))); n+=1
        cov1+=s in seen1; cov2+=(p,s) in seen2
    return {'n':n,'bits_current':l1/n if n else None,'bits_with_history':l2/n if n else None,
            'history_gain_bits':(l1-l2)/n if n else None,'coverage_current':cov1/n if n else 0,'coverage_history':cov2/n if n else 0}

def run_one(spec_index,seed):
    spec=gt.SPECS[spec_index]; config=gt.build_run_config(spec,seed); random.seed(seed)
    base.install_hooks(); sim=dtl.Sugarscape(config); sim.updateRuntimeStats(); base.ACTIVE_SIM=sim
    last_action={}; state={}; agent_records=[]; pop_records=[]; prev_pop_states={}
    current_action={int(a.ID):(0,0) for a in sim.agents}
    prev_sumw=0; prev_pw=prev_pr=0
    for tick in range(1,int(config['timesteps'])+1):
        if not sim.agents:break
        tr=base.TickTracker(sim,tick); base.ACTIVE_TRACKER=tr; sim.doTimestep(); base.ACTIVE_TRACKER=None
        for aid,a in tr.actions.items():current_action[int(aid)]=tuple(map(int,a))
        living={int(a.ID) for a in sim.agents}
        # initialize newborn/replacement states lazily
        for aid in living:
            if aid not in state:
                v=current_action.get(aid,(0,0)); state[aid]={'h':heading(v),'phi':0,'W':0,'R':0,'last':v,'prev_state':None}
        events=0; jw=0; rflips=0
        for aid in list(living):
            s=state[aid]; v=current_action.get(aid,s['last'])
            if v!=s['last']:
                old=s['last']; dw=winding_step(old,v); rev=int(pure_reversal(old,v)); events+=1; jw+=dw; rflips+=rev
                oldstate=(s['h'],s['phi'],s['W'],s['R'])
                s['phi']+=1; s['W']+=dw; s['R']^=rev; s['h']=heading(v); s['last']=v
                newstate=(s['h'],s['phi'],s['W'],s['R'])
                target=(s['h'],event_kind(old,v),dw,rev)
                rec={'target':target,
                     'h':(s['h'],),'h_prev':(oldstate[0],),
                     'h_phi':(s['h'],s['phi']),'h_phi_prev':(oldstate[0],oldstate[1]),
                     'h_phi_W':(s['h'],s['phi'],s['W']),'h_phi_W_prev':(oldstate[0],oldstate[1],oldstate[2]),
                     'h_phi_W_R':newstate,'h_phi_W_R_prev':oldstate}
                agent_records.append(rec)
        # population state after events
        N=len(living); B=int(sim.runtimeStats.get('agentsBorn',0))+int(sim.runtimeStats.get('agentsReplaced',0)); D=int(sim.runtimeStats.get('agentDeaths',0))
        m1,m2=m_orders(current_action,living); Phi=events/max(1,N)
        sumW=sum(state[aid]['W'] for aid in living); PW=sumW&1; PR=sum(state[aid]['R'] for aid in living)&1
        hist=pairwise_hist([state[aid]['W'] for aid in living]); ps=pair_summary(hist)
        base_state=(N,B,D,q01(m1),q01(m2))
        s1=base_state+(q01(min(0.999999,Phi)),)
        s2=s1+(slog(sumW),slog(jw))
        s3=s2+(PW,PR)
        s4=s3+ps
        s5=s3+(hist,)
        target=(B,D,q01(min(0.999999,Phi)),slog(jw),PW^prev_pw,PR^prev_pr,q01(m1),q01(m2))
        row={'target':target,'P0':base_state,'P1':s1,'P2':s2,'P3':s3,'P4_summary':s4,'P5_pair_exact':s5}
        for k in ('P0','P1','P2','P3','P4_summary','P5_pair_exact'):
            row[k+'_prev']=prev_pop_states.get(k); prev_pop_states[k]=row[k]
        pop_records.append(row); prev_sumw=sumW; prev_pw=PW; prev_pr=PR
    base.ACTIVE_SIM=None
    return {'spec':spec.target_id,'seed':seed,'agent_records':agent_records,'pop_records':pop_records,'events':len(agent_records),'ticks':len(pop_records)}

def analyze(runs,seeds):
    split=max(1,int(seeds*0.6)); by={}
    for spec in [s.target_id for s in gt.SPECS]:
        rr=[r for r in runs if r['spec']==spec]; train=[r for r in rr if r['seed']<=split]; test=[r for r in rr if r['seed']>split]
        atr=[x for r in train for x in r['agent_records']]; ate=[x for r in test for x in r['agent_records']]
        ptr=[x for r in train for x in r['pop_records']]; pte=[x for r in test for x in r['pop_records']]
        by[spec]={'runs':len(rr),'agent_events':sum(r['events'] for r in rr),'ticks':sum(r['ticks'] for r in rr),
                  'agent_ladder':{k:score(atr,ate,k,'target') for k in ('h','h_phi','h_phi_W','h_phi_W_R')},
                  'population_ladder':{k:score(ptr,pte,k,'target') for k in ('P0','P1','P2','P3','P4_summary','P5_pair_exact')}}
    # pooled across regimes, still held out by seed
    train=[r for r in runs if r['seed']<=split]; test=[r for r in runs if r['seed']>split]
    atr=[x for r in train for x in r['agent_records']]; ate=[x for r in test for x in r['agent_records']]
    ptr=[x for r in train for x in r['pop_records']]; pte=[x for r in test for x in r['pop_records']]
    return {'schema':'sugarscape.event-markov-closure.v1','seeds':seeds,'train_seed_max':split,
            'definitions':{'event':'agent velocity changes','phi':'cumulative event count','W':'signed projective heading winding on 4-circle','R':'pure reversal parity',
                           'history_gain_bits':'held-out bits/event or bits/tick saved by adding previous state to current state; near zero supports first-order Markov closure'},
            'pooled':{'agent_ladder':{k:score(atr,ate,k,'target') for k in ('h','h_phi','h_phi_W','h_phi_W_R')},
                      'population_ladder':{k:score(ptr,pte,k,'target') for k in ('P0','P1','P2','P3','P4_summary','P5_pair_exact')}},
            'by_replication':by}

def main():
    p=argparse.ArgumentParser(); p.add_argument('--seeds',type=int,default=5); p.add_argument('--jobs',type=int,default=6); p.add_argument('--output',type=Path,default=Path('build/event-markov-closure.json')); a=p.parse_args()
    futures=[]; runs=[]
    with ProcessPoolExecutor(max_workers=a.jobs) as pool:
        for si in range(len(gt.SPECS)):
            for seed in range(1,a.seeds+1):futures.append(pool.submit(run_one,si,seed))
        for n,f in enumerate(as_completed(futures),1):
            r=f.result(); runs.append(r); print(f'{n}/{len(futures)} {r["spec"]} seed {r["seed"]}',flush=True)
    runs.sort(key=lambda r:([s.target_id for s in gt.SPECS].index(r['spec']),r['seed']))
    out=analyze(runs,a.seeds); a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps(out,indent=2,sort_keys=True)+'\n'); print(a.output)
if __name__=='__main__':main()
