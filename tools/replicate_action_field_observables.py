#!/usr/bin/env python3
"""Run the six canonical Sugarscape replications and test action-jet sufficiency.

Analysis-only instrument: it observes the stock vendored DTL engine without
changing its decisions. Absolute coordinates are used transiently only to
recover the torus translation executed by an agent and are then discarded.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
from concurrent.futures import ProcessPoolExecutor, as_completed
import json
import math
from pathlib import Path
import random
import statistics
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))
import generate_targets as gt  # noqa: E402
from sugarscape import agent as agent_module  # noqa: E402
from sugarscape import environment as environment_module  # noqa: E402
from sugarscape import sugarscape as dtl  # noqa: E402

TRAIN_MAX_SEED = 20
DEFAULT_SEEDS = 30
FEATURES = (
    "action_now", "action_projective", "derivative_projective",
    "jet_projective", "jet_projective_plus_visibility", "history4", "jet_exact",
)
HIDDEN_FEATURES = ("action_now", "action_projective", "jet_projective", "history4")
CATEGORICAL_TARGETS = (
    "movement", "vision", "sugar_metabolism", "spice_metabolism", "max_age",
    "tribe", "sex", "wealth_bucket", "age_bucket",
)
REGRESSION_TARGETS = ("wealth", "age", "time_to_live")
ACTION_ONLY_RUN_FEATURES = (
    "mean_action_l1", "rest_fraction", "action_entropy_bits",
    "horizontal_fraction", "vertical_fraction",
)
FULL_JET_RUN_FEATURES = ACTION_ONLY_RUN_FEATURES + (
    "mean_phase_l1", "mean_shift_l1", "number_level_mean",
    "shift_coherence_mean", "projective_entropy_bits", "unique_projective_per_1000",
)

ACTIVE_TRACKER: "TickTracker | None" = None
ACTIVE_SIM: Any = None
ORIGINALS: dict[str, Any] = {}


def torus_delta(raw: int, size: int) -> int:
    half = size / 2
    while raw > half:
        raw -= size
    while raw < -half:
        raw += size
    return int(raw)


def projective_pair(lead: int, lag: int) -> tuple[Any, ...]:
    if lead == 0 and lag == 0:
        return ("zero",)
    divisor = math.gcd(abs(int(lead)), abs(int(lag))) or 1
    return ("ray", int(lead) // divisor, int(lag) // divisor)


def build_jet(history: list[tuple[int, int]]) -> dict[str, Any] | None:
    if len(history) < 4:
        return None
    a0, a1, a2, a3 = history[-1], history[-2], history[-3], history[-4]
    ax = (a0[0], a1[0], a2[0], a3[0]); ay = (a0[1], a1[1], a2[1], a3[1])
    coords = (
        ax[0], ax[1], ax[0]-ax[1], ax[1]-ax[2],
        ax[0]-2*ax[1]+ax[2], ax[1]-2*ax[2]+ax[3],
        ay[0], ay[1], ay[0]-ay[1], ay[1]-ay[2],
        ay[0]-2*ay[1]+ay[2], ay[1]-2*ay[2]+ay[3],
    )
    pairs = ((0,1),(2,3),(4,5),(6,7),(8,9),(10,11))
    wheels = tuple(projective_pair(coords[i], coords[j]) for i,j in pairs)
    number_level = sum(1 for i,j in pairs if coords[i] or coords[j])
    history4 = tuple(value for action in (a0,a1,a2,a3) for value in action)
    reconstructed = (
        coords[0], coords[6], coords[1], coords[7],
        coords[1]-coords[3], coords[7]-coords[9],
        coords[5]-coords[1]+2*(coords[1]-coords[3]),
        coords[11]-coords[7]+2*(coords[7]-coords[9]),
    )
    if reconstructed != history4:
        raise AssertionError((coords, history4, reconstructed))
    return {
        "coords": coords, "wheels": wheels, "history4": history4,
        "number_level": number_level, "shift": (coords[4], coords[10]),
        "features": {
            "action_now": a0,
            "action_projective": (wheels[0], wheels[3]),
            "derivative_projective": (wheels[1], wheels[2], wheels[4], wheels[5]),
            "jet_projective": wheels,
            "history4": history4,
            "jet_exact": coords,
        },
    }


def visible_agent_ids(agent: Any) -> tuple[int, ...]:
    cell = getattr(agent, "cell", None); ranges = getattr(cell, "ranges", None)
    if cell is None or not isinstance(ranges, dict): return ()
    try:
        vision = max(0, int(math.floor(float(agent.findVision()))))
        vision = min(vision, int(cell.environment.maxCellDistance))
    except Exception:
        return ()
    ids: set[int] = set()
    for radius in range(1, vision+1):
        for candidate in ranges.get(radius, {}):
            other = getattr(candidate, "agent", None)
            if other is None or other is agent: continue
            try: alive = other.isAlive()
            except Exception: alive = getattr(other, "alive", False)
            if alive: ids.add(int(other.ID))
    return tuple(sorted(ids))


class TickTracker:
    def __init__(self, sim: Any, tick: int):
        self.sim=sim; self.tick=tick; self.actions={}; self.visibility={}
        self.field_edges=0; self.combat_events=0
        self.sugar_create=Counter(); self.sugar_annihilate=Counter()
    def action(self, agent: Any, target: Any) -> None:
        source=getattr(agent,"cell",None)
        if source is None or target is None: return
        dx=torus_delta(int(target.x)-int(source.x),int(self.sim.environment.width))
        dy=torus_delta(int(target.y)-int(source.y),int(self.sim.environment.height))
        self.actions[int(agent.ID)]=(dx,dy)


def install_hooks() -> None:
    if ORIGINALS: return
    ORIGINALS.update({
        "gotoCell":agent_module.Agent.gotoCell,
        "moveToBestCell":agent_module.Agent.moveToBestCell,
        "doCombat":agent_module.Agent.doCombat,
        "doUniversalIncome":agent_module.Agent.doUniversalIncome,
        "doMetabolism":agent_module.Agent.doMetabolism,
        "environment_doTimestep":environment_module.Environment.doTimestep,
    })
    def goto_cell(self: Any, cell: Any) -> Any:
        tr=ACTIVE_TRACKER
        if (tr is not None and ACTIVE_SIM is tr.sim and cell is not None
            and getattr(self,"cell",None) is not None
            and int(getattr(self,"born",self.timestep)) < int(self.timestep)
            and int(getattr(self,"lastMovedTimestep",-1)) != int(self.timestep)):
            tr.action(self,cell)
        return ORIGINALS["gotoCell"](self,cell)
    def move_to_best(self: Any, predeterminedMove: Any=None) -> Any:
        tr=ACTIVE_TRACKER
        if tr is not None and ACTIVE_SIM is tr.sim:
            visible=visible_agent_ids(self); tr.visibility[int(self.ID)]=len(visible); tr.field_edges+=len(visible)
        return ORIGINALS["moveToBestCell"](self,predeterminedMove)
    def do_combat(self: Any, cell: Any) -> Any:
        tr=ACTIVE_TRACKER
        if tr is not None and ACTIVE_SIM is tr.sim:
            prey=getattr(cell,"agent",None)
            if prey is not None and prey is not self: tr.combat_events+=1
        return ORIGINALS["doCombat"](self,cell)
    def do_universal_income(self: Any) -> Any:
        tr=ACTIVE_TRACKER; before=max(0.0,float(self.sugar)); out=ORIGINALS["doUniversalIncome"](self)
        if tr is not None and ACTIVE_SIM is tr.sim:
            delta=max(0.0,float(self.sugar))-before
            if delta>1e-12: tr.sugar_create["universal_income"]+=delta
        return out
    def do_metabolism(self: Any) -> Any:
        tr=ACTIVE_TRACKER
        burn=min(max(0.0,float(self.sugar)),max(0.0,float(self.findSugarMetabolism())))
        out=ORIGINALS["doMetabolism"](self)
        if tr is not None and ACTIVE_SIM is tr.sim and burn>1e-12: tr.sugar_annihilate["metabolism"]+=burn
        return out
    def env_step(self: Any, timestep: int) -> Any:
        tr=ACTIVE_TRACKER; before=None
        if tr is not None and ACTIVE_SIM is tr.sim:
            before=[max(0.0,float(cell.sugar)) for column in self.grid for cell in column]
        out=ORIGINALS["environment_doTimestep"](self,timestep)
        if before is not None:
            after=[max(0.0,float(cell.sugar)) for column in self.grid for cell in column]
            created=sum(max(0.0,b-a) for a,b in zip(before,after)); annihilated=sum(max(0.0,a-b) for a,b in zip(before,after))
            if created>1e-12: tr.sugar_create["environment"]+=created
            if annihilated>1e-12: tr.sugar_annihilate["environment"]+=annihilated
        return out
    agent_module.Agent.gotoCell=goto_cell; agent_module.Agent.moveToBestCell=move_to_best
    agent_module.Agent.doCombat=do_combat; agent_module.Agent.doUniversalIncome=do_universal_income
    agent_module.Agent.doMetabolism=do_metabolism; environment_module.Environment.doTimestep=env_step


def total_sugar_stock(sim: Any) -> float:
    cells=sum(max(0.0,float(cell.sugar)) for column in sim.environment.grid for cell in column)
    agents=sum(max(0.0,float(agent.sugar)) for agent in sim.agents if agent.isAlive())
    return cells+agents


def entropy_bits(counter: Counter[Any]) -> float:
    total=sum(counter.values())
    if total<=0: return 0.0
    return -sum((c/total)*math.log2(c/total) for c in counter.values() if c)


def new_agg() -> dict[str,Any]: return {"class":{},"reg":{},"next":{},"history":{},"survive":{}}

def add_class(agg,target,feature,key,label,count=1):
    if label is None: return
    bucket=agg["class"].setdefault(target,{}).setdefault(feature,{})
    bucket.setdefault(key,Counter())[label]+=count

def add_reg(agg,target,feature,key,value):
    if not math.isfinite(float(value)): return
    bucket=agg["reg"].setdefault(target,{}).setdefault(feature,{})
    row=bucket.setdefault(key,[0,0.0,0.0]); row[0]+=1; row[1]+=float(value); row[2]+=float(value)*float(value)

def add_special(agg,section,feature,key,label):
    bucket=agg[section].setdefault(feature,{}); bucket.setdefault(key,Counter())[label]+=1

def merge_agg(into,other):
    for target,features in other["class"].items():
        for feature,mapping in features.items():
            dst=into["class"].setdefault(target,{}).setdefault(feature,{})
            for key,counter in mapping.items(): dst.setdefault(key,Counter()).update(counter)
    for target,features in other["reg"].items():
        for feature,mapping in features.items():
            dst=into["reg"].setdefault(target,{}).setdefault(feature,{})
            for key,row in mapping.items():
                held=dst.setdefault(key,[0,0.0,0.0]); held[0]+=row[0]; held[1]+=row[1]; held[2]+=row[2]
    for section in ("next","history","survive"):
        for feature,mapping in other[section].items():
            dst=into[section].setdefault(feature,{})
            for key,counter in mapping.items(): dst.setdefault(key,Counter()).update(counter)


def classify_metrics(train,test):
    overall_train=Counter(); overall_test=Counter()
    for c in train.values(): overall_train.update(c)
    for c in test.values(): overall_test.update(c)
    total=sum(overall_test.values())
    if not total or not overall_train: return {"test_samples":total,"coverage":0.0,"accuracy_on_covered":None,"baseline_accuracy":None,"hybrid_accuracy":None}
    baseline=overall_train.most_common(1)[0][0]; baseline_correct=overall_test[baseline]
    covered=correct=hybrid=0
    for key,counter in test.items():
        n=sum(counter.values())
        if key in train and train[key]:
            pred=train[key].most_common(1)[0][0]; covered+=n; correct+=counter[pred]; hybrid+=counter[pred]
        else: hybrid+=counter[baseline]
    return {"test_samples":total,"classes_train":len(overall_train),"classes_test":len(overall_test),"coverage":covered/total,
            "accuracy_on_covered":correct/covered if covered else None,"baseline_accuracy":baseline_correct/total,"hybrid_accuracy":hybrid/total}


def regression_metrics(train,test):
    ntr=sum(int(r[0]) for r in train.values()); strn=sum(float(r[1]) for r in train.values())
    nte=sum(int(r[0]) for r in test.values()); ste=sum(float(r[1]) for r in test.values()); sste=sum(float(r[2]) for r in test.values())
    if not ntr or not nte: return {"test_samples":nte,"coverage":0.0,"r2_all":None,"r2_covered":None}
    mtr=strn/ntr; mte=ste/nte; sst=max(0.0,sste-2*mte*ste+nte*mte*mte); bsse=sste-2*mtr*ste+nte*mtr*mtr
    cn=0; cs=css=csse=0.0; hsse=0.0
    for key,row in test.items():
        n,s,ss=int(row[0]),float(row[1]),float(row[2]); seen=key in train and train[key][0]
        pred=train[key][1]/train[key][0] if seen else mtr; err=ss-2*pred*s+n*pred*pred; hsse+=err
        if seen: cn+=n; cs+=s; css+=ss; csse+=err
    cst=None
    if cn:
        cm=cs/cn; cst=max(0.0,css-2*cm*cs+cn*cm*cm)
    return {"test_samples":nte,"coverage":cn/nte,"baseline_r2_all":1-bsse/sst if sst>1e-12 else None,
            "r2_all":1-hsse/sst if sst>1e-12 else None,"r2_covered":1-csse/cst if cst and cst>1e-12 else None}


def mapping_purity(mapping):
    samples=sum(sum(c.values()) for c in mapping.values())
    if not samples: return {"keys":0,"samples":0,"sample_weighted_purity":None,"samples_on_unambiguous_keys":None,"unambiguous_key_fraction":None}
    correct=sum(c.most_common(1)[0][1] for c in mapping.values()); unambig=sum(sum(c.values()) for c in mapping.values() if len(c)==1)
    return {"keys":len(mapping),"samples":samples,"sample_weighted_purity":correct/samples,
            "samples_on_unambiguous_keys":unambig/samples,"unambiguous_key_fraction":sum(1 for c in mapping.values() if len(c)==1)/len(mapping)}


def observable_value(sim,spec):
    pop=len(sim.agents)
    if spec.variable=="population": return float(pop)
    if spec.variable=="wealth": return float(sim.runtimeStats.get("giniCoefficient",0.0))
    if spec.variable=="mean_trade_price": return float(sim.runtimeStats.get("meanTradePrice",0.0))
    if spec.variable=="majority_tribe_share": return Counter(a.tribe for a in sim.agents).most_common(1)[0][1]/pop if pop else 0.0
    return 0.0


def score_target(samples,target):
    if not samples: return None
    probs=gt.bin_samples(samples,target["support"],target["bins"]); carried=distance=0.0
    for i,expected in enumerate(target["probs"]):
        carried+=probs[i]-expected; distance+=abs(carried)*(target["bins"][i+1]-target["bins"][i])
    support=target["bins"][-1]-target["bins"][0]
    return max(0.0,min(1.0,1-distance/support)) if support>0 else None


def corr(left,right,lag=0):
    if lag>0: a,b=left[lag:],right[:-lag]
    elif lag<0: a,b=left[:lag],right[-lag:]
    else: a,b=left,right
    if len(a)<4 or len(a)!=len(b): return None
    ma,mb=statistics.fmean(a),statistics.fmean(b); da=[x-ma for x in a]; db=[x-mb for x in b]
    va=sum(x*x for x in da); vb=sum(x*x for x in db)
    if va<=1e-12 or vb<=1e-12: return None
    return sum(x*y for x,y in zip(da,db))/math.sqrt(va*vb)


def run_seed(spec_index,seed,phase):
    global ACTIVE_TRACKER,ACTIVE_SIM
    spec=gt.SPECS[spec_index]; config=gt.build_run_config(spec,seed); random.seed(seed)
    sim=dtl.Sugarscape(config); sim.updateRuntimeStats(); ACTIVE_SIM=sim
    histories=defaultdict(list); pending={}; agg=new_agg(); action_graph=set(); field_graph=set(); last_agent_node={}; last_field_node=None; field_history=[]
    target_samples=[]; run_node_counts=Counter(); run_action_counts=Counter(); tick_coherence=[]; macro_values=[]; micro_total_series=[]; field_shift_series=[]
    totals=Counter(); sample_count=0; sum_action=sum_phase=sum_shift=sum_number=0.0; horizontal=vertical=rests=0; recon_abs=0.0; recon_ticks=0
    timesteps=int(config["timesteps"]); window_start=timesteps-gt.WINDOW_TICKS
    for tick in range(1,timesteps+1):
        if not sim.agents: break
        ids_before={int(a.ID) for a in sim.agents}; dead_before=len(sim.deadAgents); repl_before=len(sim.replacedAgents); stock_before=total_sugar_stock(sim)
        tr=TickTracker(sim,tick); ACTIVE_TRACKER=tr; sim.doTimestep(); ACTIVE_TRACKER=None; stock_after=total_sugar_stock(sim)
        living={int(a.ID):a for a in sim.agents}; newly_dead=sim.deadAgents[dead_before:]; newly_repl=sim.replacedAgents[repl_before:]
        for a in newly_dead:
            residual=max(0.0,float(a.sugar))
            if residual>1e-12: tr.sugar_annihilate["death_residual"]+=residual
        for a in newly_repl:
            amount=max(0.0,float(a.sugar))
            if amount>1e-12: tr.sugar_create["replacement_endowment"]+=amount
        ids_after=set(living); created=ids_after-ids_before; replacements={int(a.ID) for a in newly_repl}; agent_plus=len(created); agent_minus=len(newly_dead)
        xplus=sum(tr.sugar_create.values()); xminus=sum(tr.sugar_annihilate.values()); reconciliation=(stock_after-stock_before)-(xplus-xminus)
        recon_abs+=abs(reconciliation); recon_ticks+=int(abs(reconciliation)>1e-7)
        totals["sugar_create"]+=xplus; totals["sugar_annihilate"]+=xminus; totals["agent_create"]+=agent_plus; totals["agent_annihilate"]+=agent_minus
        totals["field_edges"]+=tr.field_edges; totals["combat_events"]+=tr.combat_events; totals["births"]+=max(0,agent_plus-len(replacements)); totals["replacements"]+=len(replacements)
        for kind,val in tr.sugar_create.items(): totals[f"sugar_create.{kind}"]+=val
        for kind,val in tr.sugar_annihilate.items(): totals[f"sugar_annihilate.{kind}"]+=val
        if tick>window_start:
            for identifier,prior in pending.items():
                for feature,key in prior["features"].items():
                    add_special(agg,"survive",feature,key,int(identifier in ids_after))
                    if identifier in tr.actions: add_special(agg,"next",feature,key,tr.actions[identifier])
        for identifier,action in tr.actions.items():
            histories[identifier].append(action); histories[identifier]=histories[identifier][-4:]
        field_history.append((float(xplus),float(xminus),int(agent_plus),int(agent_minus))); field_history=field_history[-3:]
        field_shift_total=0.0
        if len(field_history)>=2:
            curr,prev=field_history[-1],field_history[-2]; field_node=tuple(projective_pair(int(round(curr[i])),int(round(prev[i]))) for i in range(4))
            if last_field_node is not None: field_graph.add((last_field_node,field_node))
            last_field_node=field_node
        if len(field_history)>=3:
            curr,prev,prev2=field_history[-1],field_history[-2],field_history[-3]; field_shift_total=sum(abs(curr[i]-2*prev[i]+prev2[i]) for i in range(4))
        current_pending={}; tick_sum_x=tick_sum_y=tick_shift_total=0
        for identifier,agent in living.items():
            jet=build_jet(histories.get(identifier,[]))
            if jet is None: continue
            node=jet["wheels"]; prevnode=last_agent_node.get(identifier)
            if prevnode is not None: action_graph.add((prevnode,node))
            last_agent_node[identifier]=node
            if tick<=window_start: continue
            visibility=int(tr.visibility.get(identifier,0)); features=dict(jet["features"]); features["jet_projective_plus_visibility"]=(node,"field" if visibility else "none")
            wealth=float(agent.sugar+agent.spice)
            labels={"movement":int(round(float(agent.movement))),"vision":int(round(float(agent.vision))),"sugar_metabolism":int(round(float(agent.sugarMetabolism))),
                    "spice_metabolism":int(round(float(agent.spiceMetabolism))),"max_age":int(round(float(agent.maxAge))),"tribe":None if agent.tribe is None else int(agent.tribe),
                    "sex":str(agent.sex),"wealth_bucket":int(min(40,max(0,math.floor(wealth/25)))),"age_bucket":int(max(0,agent.age)//10)}
            try: ttl=float(agent.findTimeToLive())
            except Exception: ttl=float("nan")
            regs={"wealth":wealth,"age":float(agent.age),"time_to_live":ttl}
            for feature,key in features.items():
                if feature in HIDDEN_FEATURES:
                    for target,label in labels.items(): add_class(agg,target,feature,key,label)
                    for target,value in regs.items(): add_reg(agg,target,feature,key,value)
                add_special(agg,"history",feature,key,jet["history4"])
            current_pending[identifier]={"features":features}; run_node_counts[node]+=1; action=jet["features"]["action_now"]; run_action_counts[action]+=1; sample_count+=1
            al1=abs(jet["coords"][0])+abs(jet["coords"][6]); pl1=abs(jet["coords"][2])+abs(jet["coords"][8]); sl1=abs(jet["coords"][4])+abs(jet["coords"][10])
            sum_action+=al1; sum_phase+=pl1; sum_shift+=sl1; sum_number+=jet["number_level"]; rests+=int(action==(0,0)); horizontal+=int(action[0]!=0 and action[1]==0); vertical+=int(action[1]!=0 and action[0]==0)
            tick_sum_x+=jet["shift"][0]; tick_sum_y+=jet["shift"][1]; tick_shift_total+=abs(jet["shift"][0])+abs(jet["shift"][1])
        pending=current_pending
        if tick>window_start:
            coherent=abs(tick_sum_x)+abs(tick_sum_y); tick_coherence.append(coherent/tick_shift_total if tick_shift_total else 0.0)
            micro_total_series.append(float(tick_shift_total)); field_shift_series.append(float(field_shift_total)); macro_values.append(observable_value(sim,spec)); pop=len(sim.agents)
            if spec.variable=="wealth": target_samples.extend(a.sugar+a.spice for a in sim.agents)
            elif spec.variable=="population": target_samples.append(float(pop))
            elif spec.variable=="majority_tribe_share":
                if pop: target_samples.append(Counter(a.tribe for a in sim.agents).most_common(1)[0][1]/pop)
            elif spec.variable=="mean_trade_price": target_samples.append(float(sim.runtimeStats.get("meanTradePrice",0.0)))
    target=json.loads((ROOT/"targets"/f"{spec.target_id}.json").read_text()); score=score_target(target_samples,target)
    macro_delta_abs=[abs(b-a) for a,b in zip(macro_values,macro_values[1:])]; micro_delta=micro_total_series[1:]
    lag_macro={str(l):corr(macro_delta_abs,micro_delta,l) for l in range(-3,4)}; lag_field={str(l):corr(field_shift_series,micro_total_series,l) for l in range(-3,4)}
    feats={"mean_action_l1":sum_action/sample_count if sample_count else 0.0,"rest_fraction":rests/sample_count if sample_count else 0.0,
           "action_entropy_bits":entropy_bits(run_action_counts),"horizontal_fraction":horizontal/sample_count if sample_count else 0.0,"vertical_fraction":vertical/sample_count if sample_count else 0.0,
           "mean_phase_l1":sum_phase/sample_count if sample_count else 0.0,"mean_shift_l1":sum_shift/sample_count if sample_count else 0.0,"number_level_mean":sum_number/sample_count if sample_count else 0.0,
           "shift_coherence_mean":statistics.fmean(tick_coherence) if tick_coherence else 0.0,"projective_entropy_bits":entropy_bits(run_node_counts),
           "unique_projective_per_1000":len(run_node_counts)*1000/sample_count if sample_count else 0.0}
    run={"spec":spec.target_id,"seed":seed,"phase":phase,"completed_ticks":int(sim.timestep),"final_population":len(sim.agents),"final_gini":float(sim.runtimeStats.get("giniCoefficient",0.0)),
         "window_mean":statistics.fmean(target_samples) if target_samples else None,"target_match_score":score,"action_samples":sample_count,"action_features":feats,"node_counts":run_node_counts,
         "field_totals":dict(totals),"field_accounting":{"absolute_reconciliation":recon_abs,"ticks_with_reconciliation":recon_ticks},
         "lag_micro_shift_vs_macro_change":lag_macro,"lag_micro_shift_vs_field_shift":lag_field}
    ACTIVE_SIM=None
    return run,agg,action_graph,field_graph


def process_spec(spec_index,seeds):
    install_hooks(); train=new_agg(); test=new_agg(); runs=[]; action_graph=set(); field_graph=set(); split=min(TRAIN_MAX_SEED,max(1,seeds*2//3))
    for seed in range(1,seeds+1):
        phase="train" if seed<=split else "test"; run,agg,ag,fg=run_seed(spec_index,seed,phase); runs.append(run); merge_agg(train if phase=="train" else test,agg); action_graph.update(ag); field_graph.update(fg)
        print(f"{gt.SPECS[spec_index].target_id} seed {seed}/{seeds} done",flush=True)
    return {"spec_index":spec_index,"spec":gt.SPECS[spec_index].target_id,"train":train,"test":test,"runs":runs,"action_graph":action_graph,"field_graph":field_graph}


def graph_distances(edges,source):
    graph=defaultdict(set)
    for a,b in edges: graph[a].add(b); graph[b].add(a)
    dist={source:0}; q=deque([source])
    while q:
        n=q.popleft()
        for nxt in graph.get(n,()):
            if nxt not in dist: dist[nxt]=dist[n]+1; q.append(nxt)
    return dist


def mean_dicts(dicts):
    keys=sorted({k for d in dicts for k in d}); out={}
    for key in keys:
        vals=[float(d[key]) for d in dicts if d.get(key) is not None and math.isfinite(float(d[key]))]; out[key]=statistics.fmean(vals) if vals else None
    return out


def standardizer(rows,names):
    means={}; scales={}
    for n in names:
        vals=[float(r["action_features"][n]) for r in rows]; means[n]=statistics.fmean(vals); sd=statistics.pstdev(vals) if len(vals)>1 else 0.0; scales[n]=sd if sd>1e-12 else 1.0
    return means,scales

def vector(row,names,means,scales): return [(float(row["action_features"][n])-means[n])/scales[n] for n in names]

def experiment_identity(runs,names):
    train=[r for r in runs if r["phase"]=="train"]; test=[r for r in runs if r["phase"]=="test"]; means,scales=standardizer(train,names); centroids={}
    for spec in sorted({r["spec"] for r in train}):
        vs=[vector(r,names,means,scales) for r in train if r["spec"]==spec]; centroids[spec]=[statistics.fmean(v[i] for v in vs) for i in range(len(names))]
    correct=0; confusion=Counter()
    for r in test:
        v=vector(r,names,means,scales); pred=min(centroids,key=lambda s:sum((a-b)**2 for a,b in zip(v,centroids[s]))); correct+=int(pred==r["spec"]); confusion[(r["spec"],pred)]+=1
    return {"features":list(names),"test_runs":len(test),"accuracy":correct/len(test) if test else None,"confusion":[{"actual":a,"predicted":p,"count":n} for (a,p),n in sorted(confusion.items())]}


def knn_result(runs,names,outcome,k=3):
    train=[r for r in runs if r["phase"]=="train" and r.get(outcome) is not None]; test=[r for r in runs if r["phase"]=="test" and r.get(outcome) is not None]
    if len(train)<k or not test: return {"r2":None,"test_runs":len(test)}
    means,scales=standardizer(train,names); trainv=[(vector(r,names,means,scales),float(r[outcome])) for r in train]; ys=[float(r[outcome]) for r in test]; preds=[]
    for r in test:
        v=vector(r,names,means,scales); nearest=sorted(trainv,key=lambda z:sum((a-b)**2 for a,b in zip(v,z[0])))[:k]; preds.append(statistics.fmean(y for _,y in nearest))
    ym=statistics.fmean(ys); sst=sum((y-ym)**2 for y in ys); sse=sum((y-p)**2 for y,p in zip(ys,preds)); baseline=statistics.fmean(y for _,y in trainv); bsse=sum((y-baseline)**2 for y in ys)
    return {"features":list(names),"test_runs":len(test),"r2":1-sse/sst if sst>1e-12 else None,"baseline_r2":1-bsse/sst if sst>1e-12 else None,"rmse":math.sqrt(sse/len(ys))}


def pearson_pairs(rows,names,outcome):
    out={}; valid=[r for r in rows if r.get(outcome) is not None]; ys=[float(r[outcome]) for r in valid]
    for n in names: out[n]=corr([float(r["action_features"][n]) for r in valid],ys,0) if len(valid)>=4 else None
    return out


def summarize(spec_results,seeds):
    global_train=new_agg(); global_test=new_agg(); all_runs=[]; action_edges=set(); field_edges=set(); per_spec={}
    for result in spec_results:
        merge_agg(global_train,result["train"]); merge_agg(global_test,result["test"]); all_runs.extend(result["runs"]); action_edges.update(result["action_graph"]); field_edges.update(result["field_graph"])
    zero=("zero",); rest_agent=(zero,)*6; rest_field=(zero,)*4; action_shell=graph_distances(action_edges,rest_agent); field_shell=graph_distances(field_edges,rest_field)
    for result in spec_results:
        spec=result["spec"]; train=result["train"]; test=result["test"]; runs=result["runs"]
        recon={f:{**classify_metrics(train["history"].get(f,{}),test["history"].get(f,{})),"train_mapping_purity":mapping_purity(train["history"].get(f,{}))} for f in FEATURES}
        next_action={f:classify_metrics(train["next"].get(f,{}),test["next"].get(f,{})) for f in FEATURES}
        hidden_cls={t:{f:classify_metrics(train["class"].get(t,{}).get(f,{}),test["class"].get(t,{}).get(f,{})) for f in HIDDEN_FEATURES} for t in CATEGORICAL_TARGETS}
        hidden_reg={t:{f:regression_metrics(train["reg"].get(t,{}).get(f,{}),test["reg"].get(t,{}).get(f,{})) for f in HIDDEN_FEATURES} for t in REGRESSION_TARGETS}
        survival={f:classify_metrics(train["survive"].get(f,{}),test["survive"].get(f,{})) for f in HIDDEN_FEATURES}
        shell_means=[]; unresolved=[]
        for r in runs:
            counts=r["node_counts"]; total=sum(counts.values()); known=sum(c for n,c in counts.items() if n in action_shell); shell_means.append(sum(action_shell[n]*c for n,c in counts.items() if n in action_shell)/known if known else None); unresolved.append(1-known/total if total else 0.0); r["node_counts"]=None
        expected=json.loads((ROOT/"targets"/f"{spec}.json").read_text()).get("generation",{}).get("stats",{})
        per_spec[spec]={
            "replication":{"observed":{"seeds":len(runs),"mean_final_gini":statistics.fmean(float(r["final_gini"]) for r in runs),"mean_final_population":statistics.fmean(float(r["final_population"]) for r in runs),
                                       "mean_window_mean":statistics.fmean(float(r["window_mean"]) for r in runs if r["window_mean"] is not None),"mean_target_match_score":statistics.fmean(float(r["target_match_score"]) for r in runs if r["target_match_score"] is not None)},"published_generation_stats":expected},
            "history_reconstruction":recon,"next_action_prediction":next_action,"hidden_state_classification":hidden_cls,"hidden_state_regression":hidden_reg,"next_tick_survival":survival,
            "transition_shell":{"mean_shell_over_runs":statistics.fmean(x for x in shell_means if x is not None) if any(x is not None for x in shell_means) else None,"mean_unresolved_fraction":statistics.fmean(unresolved)},
            "result_prediction":{"target_match_action_only":knn_result(runs,ACTION_ONLY_RUN_FEATURES,"target_match_score"),"target_match_full_jet":knn_result(runs,FULL_JET_RUN_FEATURES,"target_match_score"),
                                 "window_mean_action_only":knn_result(runs,ACTION_ONLY_RUN_FEATURES,"window_mean"),"window_mean_full_jet":knn_result(runs,FULL_JET_RUN_FEATURES,"window_mean"),
                                 "feature_correlations_target_match":pearson_pairs(runs,FULL_JET_RUN_FEATURES,"target_match_score"),"feature_correlations_window_mean":pearson_pairs(runs,FULL_JET_RUN_FEATURES,"window_mean")},
            "lead_lag":{"micro_shift_vs_macro_change":mean_dicts([r["lag_micro_shift_vs_macro_change"] for r in runs]),"micro_shift_vs_field_shift":mean_dicts([r["lag_micro_shift_vs_field_shift"] for r in runs])},
            "field":{"mean_accounting_abs_reconciliation":statistics.fmean(r["field_accounting"]["absolute_reconciliation"] for r in runs),"runs_with_any_reconciliation":sum(r["field_accounting"]["ticks_with_reconciliation"]>0 for r in runs),
                     "mean_totals":mean_dicts([{k:float(v) for k,v in r["field_totals"].items()} for r in runs])},
            "run_features":{n:statistics.fmean(float(r["action_features"][n]) for r in runs) for n in FULL_JET_RUN_FEATURES},
        }
    pooled_history={f:{**classify_metrics(global_train["history"].get(f,{}),global_test["history"].get(f,{})),"train_mapping_purity":mapping_purity(global_train["history"].get(f,{}))} for f in FEATURES}
    pooled_next={f:classify_metrics(global_train["next"].get(f,{}),global_test["next"].get(f,{})) for f in FEATURES}
    pooled_cls={t:{f:classify_metrics(global_train["class"].get(t,{}).get(f,{}),global_test["class"].get(t,{}).get(f,{})) for f in HIDDEN_FEATURES} for t in CATEGORICAL_TARGETS}
    pooled_reg={t:{f:regression_metrics(global_train["reg"].get(t,{}).get(f,{}),global_test["reg"].get(t,{}).get(f,{})) for f in HIDDEN_FEATURES} for t in REGRESSION_TARGETS}
    return {"schema":"sugarscape.action-field.replication-study.v1","commit":"7b610e077a2e6cfa74cb938423dff9e7edc26107","seeds_per_replication":seeds,
            "train_seed_max":min(TRAIN_MAX_SEED,max(1,seeds*2//3)),"replications":[s.target_id for s in gt.SPECS],
            "algebraic_checks":{"mature_exact_jet_is_bijective_with_last_four_actions":True,"definition":"finite-difference coordinates are an invertible linear reparameterization of four action samples"},
            "pooled":{"history_reconstruction":pooled_history,"next_action_prediction":pooled_next,"hidden_state_classification":pooled_cls,"hidden_state_regression":pooled_reg,
                      "experiment_identity":{"action_only":experiment_identity(all_runs,ACTION_ONLY_RUN_FEATURES),"full_jet":experiment_identity(all_runs,FULL_JET_RUN_FEATURES)},
                      "transition_graph":{"agent_projective_nodes":len({n for e in action_edges for n in e}),"agent_edges":len(action_edges),"agent_rest_component_nodes":len(action_shell),
                                          "field_projective_nodes":len({n for e in field_edges for n in e}),"field_edges":len(field_edges),"field_rest_component_nodes":len(field_shell)}},
            "by_replication":per_spec,"runs":[{k:v for k,v in r.items() if k!="node_counts"} for r in all_runs]}


def main() -> int:
    p=argparse.ArgumentParser(); p.add_argument("--seeds",type=int,default=DEFAULT_SEEDS); p.add_argument("--jobs",type=int,default=4); p.add_argument("--output",type=Path,default=Path("build/action-field-replication-study.json")); args=p.parse_args()
    results=[]
    with ProcessPoolExecutor(max_workers=min(args.jobs,len(gt.SPECS))) as pool:
        futures={pool.submit(process_spec,i,args.seeds):i for i in range(len(gt.SPECS))}
        for future in as_completed(futures):
            result=future.result(); results.append(result); print(f"completed {result['spec']}",flush=True)
    results.sort(key=lambda r:r["spec_index"]); report=summarize(results,args.seeds); args.output.parent.mkdir(parents=True,exist_ok=True); args.output.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print(json.dumps({"output":str(args.output),"specs":report["replications"],"seeds":args.seeds},indent=2)); return 0

if __name__=="__main__": raise SystemExit(main())
