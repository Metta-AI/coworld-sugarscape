#!/usr/bin/env python3
from __future__ import annotations

import argparse, json, math, random, sys
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src')); sys.path.insert(0,str(ROOT/'tools'))
import generate_targets as gt  # noqa: E402
import replicate_action_field_observables as base  # noqa: E402
from sugarscape import sugarscape as dtl  # noqa: E402

HEADINGS=('0','+1','inf','-1'); HIDX={h:i for i,h in enumerate(HEADINGS)}; REST='rest'; ALPHA=0.5


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
    d=(HIDX[hb]-HIDX[ha])%4
    if d==1:return 1
    if d==3:return -1
    cross=a[0]*b[1]-a[1]*b[0]
    return 2 if cross>0 else (-2 if cross<0 else 0)

def event_kind(a,b):
    if heading(a)==REST or heading(b)==REST:return 'rest-transition'
    if pure_reversal(a,b):return 'reversal'
    if heading(a)!=heading(b):return 'turn'
    return 'speed-only'

def q01(x,bins=12):return max(0,min(bins-1,int(float(x)*bins)))
def slog(x):
    x=int(round(float(x)))
    if x==0:return 0
    return (1 if x>0 else -1)*(1+int(math.log2(abs(x))))
def m_orders(actions,living):
    if not living:return (0.0,0.0)
    z1=z2=0j
    for aid in living:
        x,y=actions.get(aid,(0,0))
        if x==0 and y==0:continue
        th=math.atan2(y,x); z1+=complex(math.cos(th),math.sin(th)); z2+=complex(math.cos(2*th),math.sin(2*th))
    n=len(living); return abs(z1/n),abs(z2/n)
def pairwise_hist(ws):
    c=Counter(ws); vals=sorted(c); out=[]
    for d in range((vals[-1]-vals[0])+1 if vals else 0):
        n=0
        for w,nw in c.items(): n+=nw*c.get(w+d,0)
        if d==0:n=sum(v*(v-1)//2 for v in c.values())
        if n:out.append((d,n if d==0 else n))
    return tuple(out)
def pair_summary(hist):
    total=sum(n for _,n in hist)
    if not total:return (0,0,0,0)
    mean=sum(d*n for d,n in hist)/total; odd=sum(n for d,n in hist if d&1)/total; mx=max(d for d,_ in hist)
    ent=0.0
    for _,n in hist:
        p=n/total; ent-=p*math.log2(p)
    return (slog(mean),q01(odd),slog(mx),q01(min(0.999999,ent/8)))

class Model:
    def __init__(self): self.ctx=defaultdict(Counter); self.base=Counter()
    def add(self,c,y):self.ctx[c][y]+=1; self.base[y]+=1
    def prob(self,c,y):
        vocab=max(1,len(self.base)); bn=sum(self.base.values()); prior=(self.base[y]+ALPHA)/(bn+ALPHA*vocab)
        cc=self.ctx.get(c); n=sum(cc.values()) if cc else 0
        return prior if not cc else (cc[y]+ALPHA*prior)/(n+ALPHA)
def score(train,test,key):
    a,b=Model(),Model(); seen_a=set(); seen_b=set()
    for r in train:
        s,p,y=r[key],r.get(key+'_prev'),r['target']; a.add(s,y); seen_a.add(s)
        if p is not None:b.add((p,s),y); seen_b.add((p,s))
    la=lb=0.0; n=ca=cb=0
    for r in test:
        s,p,y=r[key],r.get(key+'_prev'),r['target']
        if p is None:continue
        la-=math.log2(max(1e-300,a.prob(s,y))); lb-=math.log2(max(1e-300,b.prob((p,s),y))); n+=1; ca+=s in seen_a; cb+=(p,s) in seen_b
    return {'n':n,'bits_current':la/n if n else None,'bits_with_history':lb/n if n else None,'history_gain_bits':(la-lb)/n if n else None,
            'coverage_current':ca/n if n else 0.0,'coverage_history':cb/n if n else 0.0}

def agent_record(oldstate,prevstate,target):
    h,phi,W,R=oldstate
    out={'target':target,'h':(h,),'h_phi':(h,phi),'h_phi_W':(h,phi,W),'h_phi_W_R':oldstate}
    if prevstate is None:
        for k in ('h','h_phi','h_phi_W','h_phi_W_R'):out[k+'_prev']=None
    else:
        ph,pp,pw,pr=prevstate; out.update({'h_prev':(ph,), 'h_phi_prev':(ph,pp), 'h_phi_W_prev':(ph,pp,pw), 'h_phi_W_R_prev':prevstate})
    return out

def pop_states(N,B,D,m1,m2,Phi,sumW,jw,PW,PR,hist):
    p0=(slog(N),slog(B),slog(D),q01(m1),q01(m2)); p1=p0+(q01(min(.999999,Phi)),); p2=p1+(slog(sumW),slog(jw)); p3=p2+(PW,PR)
    return {'P0':p0,'P1':p1,'P2':p2,'P3':p3,'P4_summary':p3+pair_summary(hist),'P5_pair_exact':p3+(hist,)}

def run_one(spec_index,seed):
    spec=gt.SPECS[spec_index]; config=gt.build_run_config(spec,seed); random.seed(seed)
    base.install_hooks(); sim=dtl.Sugarscape(config); sim.updateRuntimeStats(); base.ACTIVE_SIM=sim
    states={}; actions={int(a.ID):(0,0) for a in sim.agents}; agent_records=[]; pop_records=[]; prior_pop=None; prior_prior_pop=None
    prev_pw=prev_pr=0
    for tick in range(1,int(config['timesteps'])+1):
        if not sim.agents:break
        tr=base.TickTracker(sim,tick); base.ACTIVE_TRACKER=tr; sim.doTimestep(); base.ACTIVE_TRACKER=None
        for aid,v in tr.actions.items():actions[int(aid)]=tuple(map(int,v))
        living={int(a.ID) for a in sim.agents}
        for aid in living:
            if aid not in states:
                v=actions.get(aid,(0,0)); states[aid]={'h':heading(v),'phi':0,'W':0,'R':0,'last':v,'prev_state':None}
        events=jw=0
        for aid in living:
            s=states[aid]; v=actions.get(aid,s['last'])
            if v==s['last']:continue
            old=s['last']; oldstate=(s['h'],s['phi'],s['W'],s['R']); prevstate=s['prev_state']; dw=winding_step(old,v); rev=int(pure_reversal(old,v))
            target=(heading(v),event_kind(old,v),dw,rev)
            agent_records.append(agent_record(oldstate,prevstate,target))
            s['prev_state']=oldstate; s['phi']+=1; s['W']+=dw; s['R']^=rev; s['h']=heading(v); s['last']=v; events+=1; jw+=dw
        N=len(living); B=int(sim.runtimeStats.get('agentsBorn',0))+int(sim.runtimeStats.get('agentsReplaced',0)); D=int(sim.runtimeStats.get('agentDeaths',0)); m1,m2=m_orders(actions,living); Phi=events/max(1,N)
        sumW=sum(states[a]['W'] for a in living); PW=sumW&1; PR=sum(states[a]['R'] for a in living)&1; hist=pairwise_hist([states[a]['W'] for a in living])
        cur=pop_states(N,B,D,m1,m2,Phi,sumW,jw,PW,PR,hist)
        flux=(slog(B),slog(D),q01(min(.999999,Phi)),slog(jw),PW^prev_pw,PR^prev_pr,q01(m1),q01(m2))
        if prior_pop is not None:
            rec={'target':flux}
            for k,v in prior_pop.items(): rec[k]=v; rec[k+'_prev']=prior_prior_pop.get(k) if prior_prior_pop else None
            pop_records.append(rec)
        prior_prior_pop=prior_pop; prior_pop=cur; prev_pw=PW; prev_pr=PR
    base.ACTIVE_SIM=None
    return {'spec':spec.target_id,'seed':seed,'agent_records':agent_records,'pop_records':pop_records,'events':len(agent_records),'ticks':len(pop_records)}

def analyze(runs,seeds):
    split=max(1,seeds//2); agent_keys=('h','h_phi','h_phi_W','h_phi_W_R'); pop_keys=('P0','P1','P2','P3','P4_summary','P5_pair_exact')
    def block(rr):
        tr=[r for r in rr if r['seed']<=split]; te=[r for r in rr if r['seed']>split]
        atr=[x for r in tr for x in r['agent_records']]; ate=[x for r in te for x in r['agent_records']]; ptr=[x for r in tr for x in r['pop_records']]; pte=[x for r in te for x in r['pop_records']]
        return {'agent_ladder':{k:score(atr,ate,k) for k in agent_keys},'population_ladder':{k:score(ptr,pte,k) for k in pop_keys},'events':sum(r['events'] for r in rr),'ticks':sum(r['ticks'] for r in rr)}
    by={spec: block([r for r in runs if r['spec']==spec]) for spec in [s.target_id for s in gt.SPECS]}
    return {'schema':'sugarscape.event-markov-closure.v2','seeds':seeds,'train_seed_max':split,
            'definitions':{'event':'velocity changes','phi':'event count','W':'signed winding on projective 4-circle','R':'pure-reversal parity','history_gain_bits':'held-out log-loss improvement from F_{t-1} after conditioning on F_t; values near zero support first-order closure'},
            'pooled':block(runs),'by_replication':by}
def main():
    p=argparse.ArgumentParser(); p.add_argument('--seeds',type=int,default=4); p.add_argument('--jobs',type=int,default=6); p.add_argument('--output',type=Path,default=Path('build/event-markov-closure-v2.json')); a=p.parse_args()
    runs=[]
    with ProcessPoolExecutor(max_workers=a.jobs) as pool:
        fs=[pool.submit(run_one,si,seed) for si in range(len(gt.SPECS)) for seed in range(1,a.seeds+1)]
        for n,f in enumerate(as_completed(fs),1):r=f.result(); runs.append(r); print(f'{n}/{len(fs)} {r["spec"]} seed {r["seed"]}',flush=True)
    runs.sort(key=lambda r:([s.target_id for s in gt.SPECS].index(r['spec']),r['seed']))
    out=analyze(runs,a.seeds); a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps(out,indent=2,sort_keys=True)+'\n'); print(a.output)
if __name__=='__main__':main()
