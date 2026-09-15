from __future__ import annotations

from dataclasses import asdict, replace
import json
import subprocess

import pytest

from dtl_sync_support import git
from test_dtl_sync_prepare import world, sync, prepare, add_pr, pr_state


def bundle(sync, world, *, edit=True):
    meta, directory, _, _ = prepare(sync, world)
    if edit:
        (directory/'src/coworld/adaptation.py').write_text('adapted\n')
    output = world.path/f'patch-{world.counter}'
    candidate = sync.prepare_patch(meta=meta, directory=directory, output=output, runner=sync.CommandRunner())
    report = dict(classification='mechanical' if edit else 'no-impact', cause='none',
        summary='Adapt the wrapper. Preserve the current contract.',
        upstream_range={'from':meta.main_pin, 'to':meta.target_sha},
        reachability=[{'path':'engine.py','symbol':'module','reached':edit,'reason':'Changed upstream module.'}],
        design_questions=[],reasoning='The recorded probe and suite cover the unchanged contract.')
    passed = sync.TestResult(True,0,5,3,0,0,2)
    verification = sync.Verification(1,meta.main_sha,meta.target_sha,candidate.patch_sha256,
        candidate.candidate_tree,True,True,False,'a'*64,'a'*64,passed,passed,None,'sha256:'+'b'*64,['perf'])
    return meta,candidate,output,report,verification


def publish(sync, world, values, **options):
    meta,candidate,patch,report,verification = values
    return sync.publish_tree(meta=meta,candidate=candidate,patch=patch/'candidate.patch',
        report=report,verification=asdict(verification),checkout=world.parent,
        directory=world.path/f'publish-{world.counter}',output=world.path/f'publication-{world.counter}',
        runner=options.pop('runner',sync.CommandRunner(env=world.env)),app_login='dtl-sync[bot]',
        app_email='123+dtl-sync[bot]@users.noreply.github.com',
        upstream_url=str(world.upstream_remote),**options)


def test_publish_reconstructs_whole_tree_and_merge_parents(sync,world):
    first = bundle(sync,world)
    result = publish(sync,world,first)
    head = result['published_head_sha']
    assert git(world.origin,'rev-parse',first[0].branch) == head
    assert git(world.origin,'show','-s','--format=%P',head) == first[0].main_sha
    assert git(world.origin,'rev-parse',head+'^{tree}') == first[1].candidate_tree
    assert git(world.origin,'show',head+':src/coworld/adaptation.py') == 'adapted'
    assert 'dtl-sync[bot]' in git(world.origin,'show','-s','--format=%an',head)
    assert git(world.parent,'status','--porcelain') == ''
    git(world.parent,'fetch','origin',head)
    git(world.parent,'push','origin',head+':refs/heads/dtl-sync/candidate')
    world.set_prs([world.pr(head=head,body=pr_state(sync,world,head))])
    (world.parent/'Dockerfile').write_text('new main image\n')
    (world.parent/'tools/dtl_sync.py').write_text('new main publisher\n')
    git(world.parent,'add','.')
    git(world.parent,'commit','-m','Advance trusted main')
    git(world.parent,'push','origin','main')
    world.main = git(world.parent,'rev-parse','HEAD')
    (world.upstream/'engine.py').write_text('third upstream revision\n')
    git(world.upstream,'commit','-am','Third upstream change')
    git(world.upstream,'push',str(world.upstream_remote),'master')
    second = bundle(sync,world,edit=False)
    assert second[0].target_sha != first[0].target_sha
    result = publish(sync,world,second)
    outgoing = result['published_head_sha']
    assert git(world.origin,'show','-s','--format=%P',outgoing).split() == [head,world.main]
    assert git(world.origin,'show',outgoing+':src/coworld/adaptation.py') == 'adapted'
    assert git(world.origin,'show',outgoing+':Dockerfile') == 'new main image'
    assert git(world.origin,'show',outgoing+':tools/dtl_sync.py') == 'new main publisher'
    assert git(world.origin,'rev-parse',outgoing+'^{tree}') == second[1].candidate_tree


@pytest.mark.parametrize('changed,failed,baseline,cause',[(True,0,0,'semantic-change'),(False,1,0,'compat-defect'),(False,1,1,'baseline-failure')])
def test_complete_red_candidate_publishes_exact_patch(sync,world,changed,failed,baseline,cause):
    values=list(bundle(sync,world))
    red=sync.TestResult(True,1,5,2,1,0,2)
    values[4]=replace(values[4],hash_new='c'*64 if changed else 'a'*64,hash_changed=changed,
        candidate_tests=red if failed else values[4].candidate_tests,
        baseline_tests=red if baseline else values[4].baseline_tests)
    result=publish(sync,world,values)
    assert (result['classification'],result['cause']) == ('needs-design',cause)
    assert result['candidate_tree'] == values[1].candidate_tree
    assert git(world.origin,'rev-parse',result['published_head_sha']+'^{tree}') == values[1].candidate_tree


@pytest.mark.parametrize('field,value',[('hash_changed',None),('pin_matches_target',False),('patch_applied',None),('hash_new','bad'),('main_sha','0'*40),('excluded_markers',[]),('excluded_markers',['perf','slow']),('reason','incomplete'),('image_id',None)])
def test_invalid_verification_never_publishes(sync,world,field,value):
    values=list(bundle(sync,world))
    values[4]=replace(values[4],**{field:value})
    with pytest.raises(sync.SyncError):publish(sync,world,values)
    assert git(world.origin,'for-each-ref','--format=%(refname)','refs/heads/dtl-sync/') == ''


@pytest.mark.parametrize('edit',[True,False])
def test_invalid_report_never_publishes_even_empty_patch(sync,world,edit):
    values=list(bundle(sync,world,edit=edit));values[3]=None
    with pytest.raises(sync.SyncError):publish(sync,world,values)
    assert git(world.origin,'for-each-ref','--format=%(refname)','refs/heads/dtl-sync/') == ''


@pytest.mark.parametrize('field,value',[('completed',False),('collected',0),('passed',True),('failed',None),('skipped',-1),('exit_code',1),('errors',1)])
def test_test_result_contract_rejects_unknown_or_inconsistent_counts(sync,world,field,value):
    values=bundle(sync,world)
    data=asdict(values[4]);data['candidate_tests'][field]=value
    with pytest.raises(sync.SyncError):sync.validate_verification(data,values[0],values[1])


def test_classification_counts_skips_separately_and_requires_inventory(sync,world):
    meta,candidate,_,report,verification=bundle(sync,world,edit=False)
    parsed=sync.validate_verification(asdict(verification),meta,candidate)
    assert parsed.candidate_tests.passed == 3 and parsed.candidate_tests.skipped == 2
    decision=sync.classify(sync.validate_report(report,meta),candidate,parsed,[])
    assert decision == ('no-impact','none')
    report['reachability'][0]['reached']=True
    assert sync.classify(sync.validate_report(report,meta),candidate,parsed,[]) == ('mechanical','none')
    report['classification']='needs-design';report['cause']='new-feature'
    assert sync.classify(sync.validate_report(report,meta),candidate,parsed,[]) == ('needs-design','new-feature')


def test_protected_edits_and_unresolved_questions_force_design(sync,world):
    meta,candidate,_,report,verification=bundle(sync,world)
    parsed=sync.validate_report(report,meta)
    assert sync.classify(parsed,replace(candidate,protected_edits=['tests/test_dtl.py']),verification,[]) == ('needs-design','protected-path-edit')
    assert sync.classify(parsed,candidate,verification,[{'id':'player-choice','question':'Expose this mechanic?'}]) == ('needs-design','none')


def test_incomplete_inventory_is_not_no_impact(sync,world):
    values=list(bundle(sync,world,edit=False));values[3]['reachability']=[]
    with pytest.raises(sync.SyncError,match='inventory'):publish(sync,world,values)


@pytest.mark.parametrize('change',['main','pr','closed'])
def test_publish_refuses_stale_heads_or_closed_pr(sync,world,change):
    head=add_pr(sync,world,{'README.md':'prior\n'})
    values=bundle(sync,world)
    if change=='main':
        (world.parent/'README.md').write_text('advanced\n');git(world.parent,'commit','-am','Advance')
        git(world.parent,'push','origin','main')
    elif change=='closed':world.set_prs([])
    else:world.set_prs([world.pr(head=world.main,body=pr_state(sync,world,head))])
    with pytest.raises(sync.SyncError,match='stale'):publish(sync,world,values)
    assert git(world.origin,'rev-parse','dtl-sync/candidate') == head


def test_unchanged_tree_updates_evidence_without_empty_commit(sync,world):
    values=bundle(sync,world)
    first=publish(sync,world,values)
    head=first['published_head_sha'];meta=values[0]
    pr=world.pr(head=head,body=pr_state(sync,world,head));pr['head']['ref']=meta.branch
    world.set_prs([pr]);world.counter+=1
    values=list(values);values[0]=replace(meta,mode='update-pr',pr_number=7,pr_head_sha=head,force=True)
    result=publish(sync,world,values)
    assert result['outcome']=='unchanged'
    assert result['published_head_sha']==head
    evidence=json.loads((world.path/f'publication-{world.counter}/publication.json').read_text())
    assert evidence['verification']['candidate_tests']['passed']==3
    assert git(world.origin,'rev-parse',meta.branch)==head


def test_retry_reconciles_exact_pushed_commit_without_pr(sync,world):
    values=bundle(sync,world);first=publish(sync,world,values)
    world.counter+=1
    second=publish(sync,world,values)
    assert second['outcome']=='reconciled'
    assert second['published_head_sha']==first['published_head_sha']


def test_report_schema_is_closed_and_matches_runtime(sync,world):
    from pathlib import Path
    meta,_,_,report,_=bundle(sync,world)
    schema=json.loads((Path(__file__).resolve().parents[1]/'tools/dtl_sync/REPORT_SCHEMA.json').read_text())
    assert schema['additionalProperties'] is False
    assert set(schema['required'])==set(report)==set(schema['properties'])
    assert sync.validate_report(report,meta).summary==report['summary']
    report['surprise']='field'
    with pytest.raises(sync.SyncError):sync.validate_report(report,meta)


@pytest.mark.parametrize('field,value',[
    ('classification','unknown'),('cause',True),('summary',''),('reasoning','x'*8001),
    ('upstream_range',{'from':'0'*40,'to':'1'*40}),
    ('reachability',[{'path':'../secret','symbol':'module','reached':False,'reason':'no'}]),
    ('reachability',[{'path':'engine.py','symbol':'module','reached':None,'reason':'no'}]),
    ('design_questions',[{'id':'not a slug','question':'Why?'}]),
    ('design_questions',[{'id':'why','question':'Why?'},{'id':'why','question':'Again?'}]),
])
def test_report_rejects_invalid_nested_contract(sync,world,field,value):
    meta,_,_,report,_=bundle(sync,world);report[field]=value
    with pytest.raises(sync.SyncError):sync.validate_report(report,meta)


def test_verification_contract_is_closed_and_hash_consistent(sync,world):
    meta,candidate,_,_,verification=bundle(sync,world)
    for data in (asdict(replace(verification,hash_changed=True)),
                 {**asdict(verification),'extra':False},
                 {k:v for k,v in asdict(verification).items() if k!='baseline_tests'}):
        with pytest.raises(sync.SyncError):sync.validate_verification(data,meta,candidate)
    data=asdict(verification);data['baseline_tests']['extra']=False
    with pytest.raises(sync.SyncError):sync.validate_verification(data,meta,candidate)



def test_new_unchanged_tree_has_no_branch_or_empty_commit(sync,world):
    values=list(bundle(sync,world,edit=False))
    meta=values[0]
    values[0]=replace(meta,target_sha=meta.main_pin,force=True,
        compare_url=f'{sync.UPSTREAM_URL}/compare/{meta.main_pin}...{meta.main_pin}')
    tree=git(world.parent,'rev-parse',meta.main_sha+'^{tree}')
    values[1]=replace(values[1],target_sha=meta.main_pin,candidate_tree=tree)
    values[3]['upstream_range']['to']=meta.main_pin
    values[3]['reachability']=[]
    values[4]=replace(values[4],target_sha=meta.main_pin,candidate_tree=tree)
    result=publish(sync,world,values)
    assert result['outcome']=='unchanged'
    assert result['classification']=='no-impact'
    assert result['published_head_sha']==meta.main_sha
    assert git(world.origin,'for-each-ref','--format=%(refname)','refs/heads/dtl-sync/')==''


def test_normal_push_refuses_concurrent_non_fast_forward(sync,world):
    head=add_pr(sync,world,{'README.md':'prior\n'})
    values=bundle(sync,world)
    raced=git(world.parent,'commit-tree',world.main+'^{tree}','-p',head,input_text='Concurrent edit\n')
    class Race(sync.CommandRunner):
        def run(self,args,**kwargs):
            if args[0]=='git' and 'push' in args:
                assert not any(arg.startswith(('--force','+')) for arg in args)
                git(world.parent,'push',str(world.origin),raced+':refs/heads/dtl-sync/candidate')
            return super().run(args,**kwargs)
    with pytest.raises(sync.SyncError,match='exited'):
        publish(sync,world,values,runner=Race(env=world.env))
    assert git(world.origin,'rev-parse','dtl-sync/candidate')==raced
    assert not (world.path/f'publication-{world.counter}/publication.json').exists()


def test_occupied_branch_cannot_be_adopted_by_name_or_author(sync,world):
    values=bundle(sync,world)
    git(world.origin,'update-ref','refs/heads/'+values[0].branch,world.main)
    with pytest.raises(sync.SyncError,match='stale branch'):
        publish(sync,world,values)
    assert git(world.origin,'rev-parse',values[0].branch)==world.main


def test_existing_pr_retry_recognizes_only_its_exact_pushed_commit(sync,world):
    prior=add_pr(sync,world,{'README.md':'prior\n'})
    values=bundle(sync,world)
    first=publish(sync,world,values)
    world.set_prs([world.pr(head=first['published_head_sha'],body=pr_state(sync,world,prior))])
    world.counter+=1
    retried=publish(sync,world,values)
    assert retried['outcome']=='reconciled'
    assert retried['published_head_sha']==first['published_head_sha']


def test_artifact_reader_rejects_duplicates_and_oversize(sync,tmp_path):
    path=tmp_path/'report.json'
    for payload in ('{"summary":"one","summary":"two"}', ' '*(sync.MAX_REPORT_BYTES+1)):
        path.write_text(payload)
        with pytest.raises(sync.SyncError):sync.read_publication_artifact(path)


def test_publish_cli_uses_only_local_git_and_fake_read_only_github(sync,world):
    import sys
    from dtl_sync_support import ROOT
    meta,candidate,patch,report,verification=bundle(sync,world)
    for name,data in [('meta',asdict(meta)),('report',report),('verify',asdict(verification))]:
        (world.path/(name+'.json')).write_text(json.dumps(data))
    env={**world.env,'GIT_CONFIG_COUNT':'1',
         'GIT_CONFIG_KEY_0':f'url.{world.upstream_remote}.insteadOf','GIT_CONFIG_VALUE_0':sync.UPSTREAM_URL}
    result=subprocess.run([sys.executable,str(ROOT/'tools/dtl_sync.py'),'publish','tree',
        '--meta',str(world.path/'meta.json'),'--candidate',str(patch/'candidate.json'),
        '--patch',str(patch/'candidate.patch'),'--report',str(world.path/'report.json'),
        '--verification',str(world.path/'verify.json'),'--checkout',str(world.parent),
        '--directory',str(world.path/'cli-publish'),'--output',str(world.path/'cli-evidence'),
        '--app-login','dtl-sync[bot]','--app-email','123+dtl-sync[bot]@users.noreply.github.com'],
        env=env,text=True,capture_output=True)
    assert result.returncode==0,result.stderr
    assert result.stdout=='pushed\n'
    data=json.loads((world.path/'cli-evidence/publication.json').read_text())
    assert git(world.origin,'rev-parse',meta.branch+'^{tree}')==candidate.candidate_tree
    assert data['verification']['excluded_markers']==['perf']


def test_remote_change_before_final_check_refuses_publication(sync,world):
    values=bundle(sync,world)
    (world.parent/'README.md').write_text('new main\n')
    git(world.parent,'commit','-am','Main moves during reconstruction')
    changed=git(world.parent,'rev-parse','HEAD')
    class Race(sync.CommandRunner):
        calls=0
        def run(self,args,**kwargs):
            if args[:3]==['git','ls-remote','--heads']:
                self.calls+=1
                if self.calls==2:
                    git(world.parent,'push',str(world.origin),'main')
            return super().run(args,**kwargs)
    with pytest.raises(sync.SyncError,match='stale remote'):
        publish(sync,world,values,runner=Race(env=world.env))
    assert git(world.origin,'rev-parse','main')==changed
    assert git(world.origin,'for-each-ref','--format=%(refname)','refs/heads/dtl-sync/')==''


def test_validation_rejects_candidate_identity_before_any_git_access(sync,world):
    meta,candidate,_,_,verification=bundle(sync,world)
    with pytest.raises(sync.SyncError,match='binding'):
        sync.validate_verification(asdict(verification),meta,replace(candidate,main_sha='0'*40))


def test_all_skipped_measurements_do_not_qualify_as_success(sync,world):
    meta,candidate,_,_,verification=bundle(sync,world)
    skipped=sync.TestResult(True,0,5,0,0,0,5)
    with pytest.raises(sync.SyncError):
        sync.validate_verification(asdict(replace(verification,candidate_tests=skipped)),meta,candidate)
