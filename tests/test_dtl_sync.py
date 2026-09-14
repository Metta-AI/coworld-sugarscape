from __future__ import annotations

from dataclasses import asdict
import json
import subprocess
import sys

import pytest

from dtl_sync_support import World, git, load_sync


@pytest.fixture
def sync():
    return load_sync()


@pytest.fixture
def world(tmp_path):
    return World(tmp_path)


def state_body(sync, world, *, head=None, pending=False):
    state = {
        "schema_version": 1,
        "open_questions": [],
        "last_publication": {
            "main_sha": world.main, "target_sha": world.second,
            "published_head_sha": head or world.main, "prompt_version": world.prompt,
        },
        "deliveries": {world.second: {"discord": {
            "status": "failed" if pending else "delivered", "remote_id": None if pending else "456",
            "attempts": 1, "last_error": "transient" if pending else None,
        }}},
    }
    return sync.STATE_START + json.dumps(state) + sync.STATE_END


def test_command_runner_preserves_argv_stdin_and_failure(sync):
    runner = sync.CommandRunner()
    literal = '$(echo unsafe); `echo unsafe`'
    result = runner.run([sys.executable, "-c", "import sys; print(sys.argv[1]); print(sys.stdin.read())", literal], input_text=literal)
    assert result.stdout.splitlines() == [literal, literal]
    with pytest.raises(sync.SyncError) as error:
        runner.run([sys.executable, "-c", "import sys; print('private-token', file=sys.stderr); sys.exit(2)"])
    assert "private-token" not in str(error.value)
    with pytest.raises(sync.SyncError, match="timed out"):
        runner.run([sys.executable, "-c", "import time; time.sleep(2)"], timeout=0.02)
    assert runner.run([sys.executable, "-c", "raise SystemExit(1)"], check=False).returncode == 1


def test_detect_resolves_master_and_unique_commit(sync, world):
    before = git(world.parent, "status", "--porcelain")
    meta = world.detect(sync)
    assert meta.main_sha == world.main
    assert meta.main_pin == world.first
    assert meta.target_sha == world.second
    assert meta.prompt_version == world.prompt
    assert meta.mode == "new-pr"
    assert meta.branch == f"dtl-sync/{world.second[:12]}-123-1"
    assert world.detect(sync, upstream_ref=world.second[:8]).target_sha == world.second
    assert before == git(world.parent, "status", "--porcelain")
    assert not (world.parent / "src/sugarscape/engine.py").exists()
    assert len(world.calls.read_text().splitlines()) == 2


@pytest.mark.parametrize("ref", ["no-such-branch", "HEAD", "--help", "a" * 40])
def test_detect_rejects_invalid_or_unreachable_commit(sync, world, ref):
    with pytest.raises(sync.SyncError):
        world.detect(sync, upstream_ref=ref)


def test_detect_rejects_ambiguous_commit(sync, world):
    # Deliberately use a fake graph resolver for the rare abbreviation-collision path.
    class Ambiguous(sync.CommandRunner):
        def run(self, args, **kwargs):
            if any(str(arg).startswith("--disambiguate=") for arg in args):
                return subprocess.CompletedProcess(args, 0, world.first + "\n" + world.second + "\n", "")
            return super().run(args, **kwargs)
    with pytest.raises(sync.SyncError, match="ambiguous"):
        sync.resolve_upstream(Ambiguous(), world.path / "ambiguous.git", str(world.upstream_remote), "abcd")


def test_detect_rejects_non_descendant_without_replay(sync, world):
    git(world.parent, "update-index", "--cacheinfo", f"160000,{world.second},src/sugarscape")
    git(world.parent, "commit", "-m", "Advance pin")
    git(world.parent, "push", "origin", "main")
    with pytest.raises(sync.SyncError, match="descendant"):
        world.detect(sync, upstream_ref=world.first)
    assert world.detect(sync, upstream_ref=world.first, replay=True).target_sha == world.first
    world.set_prs([world.pr(body=state_body(sync, world))])
    with pytest.raises(sync.SyncError, match="open sync PR"):
        world.detect(sync, upstream_ref=world.first, replay=True)


def test_detect_requires_unique_owned_pr(sync, world):
    own = world.pr(body=state_body(sync, world))
    wrong = world.pr()
    wrong["head"]["repo"]["full_name"] = "outsider/game"
    other = world.pr()
    other["user"]["login"] = "human"
    world.set_prs([wrong, other], [own])
    assert world.detect(sync).pr_number == 7
    world.set_prs([own], [{**own, "number": 8}])
    with pytest.raises(sync.SyncError, match="multiple"):
        world.detect(sync)


def test_detect_skips_matching_published_head(sync, world):
    world.set_prs([world.pr(body=state_body(sync, world))])
    assert world.detect(sync).mode == "noop"
    world.set_prs([world.pr(head="b" * 40, body=state_body(sync, world))])
    assert world.detect(sync).mode == "update-pr"


def test_force_bypasses_both_noop_paths(sync, world):
    assert world.detect(sync, upstream_ref=world.first).mode == "noop"
    assert world.detect(sync, upstream_ref=world.first, force=True).mode == "new-pr"
    world.set_prs([world.pr(body=state_body(sync, world))])
    assert world.detect(sync, force=True).mode == "update-pr"


def test_detect_retries_pending_delivery_without_evaluation(sync, world):
    world.set_prs([world.pr(body=state_body(sync, world, pending=True))])
    assert world.detect(sync).mode == "retry-alerts"


@pytest.mark.parametrize("closed", ["closed", "merged"])
def test_detect_starts_fresh_after_merge_or_close(sync, world, closed):
    pr = world.pr(body=state_body(sync, world))
    pr["state"] = "closed"
    if closed == "merged":
        pr["merged_at"] = "2026-09-14T00:00:00Z"
    world.set_prs([pr])
    meta = world.detect(sync)
    assert meta.mode == "new-pr" and meta.pr_number is None
    assert meta.branch != pr["head"]["ref"]


def test_detect_refuses_missing_or_corrupt_state(sync, world):
    for body in ["", sync.STATE_START + "{}" + sync.STATE_END, state_body(sync, world) * 2]:
        world.set_prs([world.pr(body=body)])
        with pytest.raises(sync.SyncError, match="state"):
            world.detect(sync)


def test_meta_contract_roundtrips_and_rejects_invalid_fields(sync, world):
    meta = world.detect(sync)
    output = world.path / "meta.json"
    sync.write_meta(output, meta)
    assert sync.read_meta(output) == meta
    for field, value in [("unexpected", 1), ("schema_version", True), ("force", 1),
                         ("main_sha", "bad"), ("pr_number", True), ("repository", "../repo"),
                         ("branch", "dtl-sync/../main"), ("mode", "publish")]:
        payload = {**asdict(meta), field: value}
        output.write_text(json.dumps(payload))
        with pytest.raises(sync.SyncError):
            sync.read_meta(output)
    output.write_text(" " * (sync.MAX_REPORT_BYTES + 1))
    with pytest.raises(sync.SyncError, match="size"):
        sync.read_meta(output)


def test_meta_contract_rejects_duplicate_json_keys(sync, world):
    meta = world.detect(sync)
    output = world.path / "duplicate.json"
    output.write_text(json.dumps(asdict(meta))[:-1] + ', "schema_version": 1}')
    with pytest.raises(sync.SyncError, match="duplicate"):
        sync.read_meta(output)


def test_detect_validates_repository_before_api_access(sync, world):
    with pytest.raises(sync.SyncError, match="repository"):
        sync.detect(checkout=world.parent, scratch=world.path / "bad-input",
                    repository="owner/game?redirect=other", app_login="dtl-sync[bot]",
                    run_id="123", run_attempt="1", runner=sync.CommandRunner(env=world.env))
    assert not world.calls.exists()


def test_detect_failed_publication_is_not_evaluated(sync, world):
    body = sync.STATE_START + json.dumps({"schema_version": 1, "last_publication": None, "deliveries": {}, "open_questions": []}) + sync.STATE_END
    world.set_prs([world.pr(body=body)])
    assert world.detect(sync).mode == "update-pr"


@pytest.mark.parametrize("change", ["base", "label", "prefix"])
def test_detect_ignores_unowned_pr_identity(sync, world, change):
    pr = world.pr()
    if change == "base":
        pr["base"]["ref"] = "another-base"
    elif change == "label":
        pr["labels"] = []
    else:
        pr["head"]["ref"] = "human/branch"
    world.set_prs([pr])
    assert world.detect(sync).pr_number is None


def test_detect_cli_writes_meta_without_network(sync, world):
    # Redirect the fixed production URL using this process's Git configuration.
    env = {**world.env, "GIT_CONFIG_COUNT": "1",
           "GIT_CONFIG_KEY_0": f"url.{world.upstream_remote}.insteadOf",
           "GIT_CONFIG_VALUE_0": sync.UPSTREAM_URL}
    from dtl_sync_support import ROOT
    output = world.path / "cli-meta.json"
    command = [sys.executable, str(ROOT / "tools/dtl_sync.py"), "detect",
               "--checkout", str(world.parent), "--scratch", str(world.path / "cli-scratch"),
               "--output", str(output), "--repository", "owner/game", "--app-login", "dtl-sync[bot]",
               "--run-id", "123"]
    result = subprocess.run(command, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "new-pr\n"
    assert sync.read_meta(output).target_sha == world.second


def test_detect_rejects_occupied_generated_branch(sync, world):
    branch = f"dtl-sync/{world.second[:12]}-123-1"
    git(world.parent, "push", "origin", f"HEAD:refs/heads/{branch}")
    with pytest.raises(sync.SyncError, match="already exists"):
        world.detect(sync)
