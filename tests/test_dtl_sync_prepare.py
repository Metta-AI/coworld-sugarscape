from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import subprocess

import pytest

from dtl_sync_support import World, git, load_sync


@pytest.fixture
def sync():
    return load_sync()


@pytest.fixture
def world(tmp_path):
    value = World(tmp_path)
    subprocess.run(["git", "clone", str(value.upstream_remote), str(value.parent / "src/sugarscape")],
                   check=True, capture_output=True)
    git(value.parent / "src/sugarscape", "checkout", "--detach", value.first)
    for name, content in {
        "src/coworld/adapter.py": "old adapter\n", "tests/test_dtl.py": "trusted probe\n",
        "tests/conftest.py": "trusted setup\n", "README.md": "orientation\n",
        "Dockerfile": "old image\n", "tools/dtl_sync.py": "trusted tool\n",
    }.items():
        path = value.parent / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    git(value.parent, "add", ".")
    git(value.parent, "commit", "-m", "Seed wrapper")
    git(value.parent, "push", "origin", "main")
    value.main = git(value.parent, "rev-parse", "HEAD")
    return value


def pr_state(sync, world, head, questions=None):
    return sync.STATE_START + json.dumps({
        **asdict(sync.new_state()), "schema_version": 1, "last_publication": {
            "main_sha": world.main, "target_sha": world.first,
            "published_head_sha": head, "prompt_version": world.prompt,
        }, "deliveries": {}, "open_questions": questions or [],
    }) + sync.STATE_END


def add_pr(sync, world, edits, pin=None):
    git(world.parent, "switch", "-c", "dtl-sync/candidate")
    for name, content in edits.items():
        file = world.parent / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(content)
    git(world.parent, "add", ".")
    if pin is not None:
        git(world.parent, "update-index", "--cacheinfo", f"160000,{pin},src/sugarscape")
    git(world.parent, "commit", "-m", "Previous adaptation")
    head = git(world.parent, "rev-parse", "HEAD")
    git(world.parent, "push", "origin", "HEAD:refs/heads/dtl-sync/candidate")
    git(world.parent, "switch", "main")
    world.set_prs([world.pr(head=head, body=pr_state(sync, world, head))])
    return head


def prepare(sync, world, **kwargs):
    meta = world.detect(sync)
    candidate = world.path / f"candidate-{world.counter}"
    output = world.path / f"inputs-{world.counter}"
    result = sync.prepare_inputs(
        meta=meta, checkout=world.parent, directory=candidate, output=output,
        app_login="dtl-sync[bot]", runner=sync.CommandRunner(env=world.env),
        upstream_url=str(world.upstream_remote), **kwargs,
    )
    return meta, candidate, output, result


def patch(sync, world, meta, candidate, name="patch"):
    output = world.path / name
    result = sync.prepare_patch(meta=meta, directory=candidate, output=output,
                                runner=sync.CommandRunner(env=world.env))
    return output, result


def test_prepare_stages_target_gitlink(sync, world):
    before = git(world.parent, "status", "--porcelain")
    meta, candidate, output, result = prepare(sync, world)
    assert result["outcome"] == "ready"
    assert git(candidate / "src/sugarscape", "rev-parse", "HEAD") == meta.target_sha
    assert git(candidate, "ls-files", "--stage", "src/sugarscape").split()[:2] == ["160000", meta.target_sha]
    assert git(world.parent, "status", "--porcelain") == before
    assert git(world.parent / "src/sugarscape", "rev-parse", "HEAD") == world.first
    assert (output / "upstream.diff").is_file()


def test_prepare_writes_cumulative_and_previous_ranges(sync, world):
    (world.upstream / "README").write_text("new upstream documentation\n")
    (world.upstream / "plots").mkdir()
    (world.upstream / "plots/plot.py").write_text("plot-only change\n")
    git(world.upstream, "add", ".")
    git(world.upstream, "commit", "-m", "Third")
    git(world.upstream, "push", str(world.upstream_remote), "master")
    add_pr(sync, world, {"src/coworld/prior.py": "prior adaptation\n"}, pin=world.second)
    meta, candidate, output, result = prepare(sync, world)
    assert result["outcome"] == "ready"
    assert "Second" in (output / "upstream.log").read_text()
    assert "engine.py" in (output / "upstream.diff").read_text()
    assert "engine.py" not in (output / "previous-pin.diff").read_text()
    assert "plot-only change" in (output / "upstream.diff").read_text()
    assert "plot-only change" not in (output / "upstream-filtered.diff").read_text()
    assert "prior adaptation" in (output / "wrapper.diff").read_text()


def test_prepare_preserves_prior_new_staged_and_deleted_files(sync, world):
    add_pr(sync, world, {"src/coworld/prior.py": "prior\n"})
    meta, candidate, _, _ = prepare(sync, world)
    (candidate / "src/coworld/new.py").write_text("new\n")
    (candidate / "src/coworld/adapter.py").write_text("staged\n")
    git(candidate, "add", "src/coworld/adapter.py")
    (candidate / "README.md").unlink()
    index_before = (candidate / ".git/index").read_bytes()
    output, result = patch(sync, world, meta, candidate)
    assert result.files_changed == ["README.md", "src/coworld/adapter.py", "src/coworld/new.py", "src/coworld/prior.py"]
    assert (candidate / ".git/index").read_bytes() == index_before
    payload = (output / "candidate.patch").read_bytes()
    assert hashlib.sha256(payload).hexdigest() == result.patch_sha256
    assert "src/sugarscape" not in payload.decode()
    assert git(candidate, "show", result.candidate_tree + ":src/coworld/prior.py") == "prior"
    assert git(candidate, "show", result.candidate_tree + ":src/coworld/adapter.py") == "staged"
    assert git(candidate, "ls-tree", result.candidate_tree, "README.md") == ""
    again, repeated = patch(sync, world, meta, candidate, "patch-again")
    assert repeated == result
    assert (again / "candidate.patch").read_bytes() == payload


def test_prepare_uses_main_outside_allowlist(sync, world):
    add_pr(sync, world, {"src/coworld/prior.py": "prior\n"})
    (world.parent / "Dockerfile").write_text("new image\n")
    (world.parent / "tools/dtl_sync.py").write_text("new trusted tool\n")
    git(world.parent, "commit", "-am", "Advance main")
    git(world.parent, "push", "origin", "main")
    meta, candidate, _, result = prepare(sync, world)
    assert result["outcome"] == "ready"
    assert (candidate / "Dockerfile").read_text() == "new image\n"
    _, result = patch(sync, world, meta, candidate)
    assert git(candidate, "show", result.candidate_tree + ":Dockerfile") == "new image"
    assert git(candidate, "show", result.candidate_tree + ":tools/dtl_sync.py") == "new trusted tool"
    assert result.protected_edits == []


def test_prepare_merges_main_or_pauses_on_conflict(sync, world):
    add_pr(sync, world, {"src/coworld/adapter.py": "PR change\n"})
    (world.parent / "src/coworld/adapter.py").write_text("main change\n")
    git(world.parent, "commit", "-am", "Conflicting main")
    git(world.parent, "push", "origin", "main")
    _, candidate, output, result = prepare(sync, world)
    assert result["outcome"] == "needs-human"
    assert "conflict" in result["reason"]
    assert not (output / "upstream.diff").exists()


def test_prepare_pauses_for_unapproved_human_edits(sync, world):
    head = add_pr(sync, world, {"src/coworld/prior.py": "prior\n"})
    world.set_prs([world.pr(head=head, body=pr_state(sync, world, world.main))])
    _, _, _, result = prepare(sync, world)
    assert result["outcome"] == "needs-human"
    assert "head" in result["reason"]


def test_prepare_authorized_resume_is_head_bound(sync, world):
    head = add_pr(sync, world, {"src/coworld/prior.py": "approved human edit\n"})
    world.set_prs([world.pr(head=head, body=pr_state(sync, world, world.main))])
    world.api_responses({
        "repos/owner/game/issues/comments/99": {
            "body": f"resume-sync {head}", "user": {"login": "maintainer"},
            "issue_url": "https://api.github.com/repos/owner/game/issues/7",
        },
        "repos/owner/game/collaborators/maintainer/permission": {"permission": "write"},
    })
    _, _, _, result = prepare(sync, world, resume_comment_id=99)
    assert result["outcome"] == "ready"
    world.api_responses({
        "repos/owner/game/issues/comments/99": {
            "body": f"resume-sync {world.main}", "user": {"login": "maintainer"},
            "issue_url": "https://api.github.com/repos/owner/game/issues/7",
        },
    })
    _, _, _, result = prepare(sync, world, resume_comment_id=99)
    assert result["outcome"] == "needs-human"


@pytest.mark.parametrize("kind", ["symlink", "binary", "oversize", "directory-symlink"])
def test_patch_policy_rejects_unsafe_paths_modes_and_sizes(sync, world, kind, monkeypatch):
    meta, candidate, _, _ = prepare(sync, world)
    if kind == "symlink":
        (candidate / "tools/link").symlink_to("/etc/passwd")
    elif kind == "directory-symlink":
        import shutil
        shutil.rmtree(candidate / "src/coworld")
        (candidate / "src/coworld").symlink_to(world.parent / "src/coworld", target_is_directory=True)
    elif kind == "binary":
        (candidate / "tools/binary").write_bytes(b"\x00\xff")
    else:
        monkeypatch.setattr(sync, "MAX_PATCH_BYTES", 10)
        (candidate / "README.md").write_text("oversize change\n")
    with pytest.raises(sync.SyncError):
        patch(sync, world, meta, candidate)


@pytest.mark.parametrize("name", ["../outside", "/absolute", "tools/../secret", "tools//file", "tools/.git/config"])
def test_patch_policy_rejects_noncanonical_names(sync, name):
    with pytest.raises(sync.SyncError):
        sync.path_is_allowed(name)


def test_prepare_records_protected_edits_without_shipping_them(sync, world):
    meta, candidate, _, _ = prepare(sync, world)
    (candidate / "tests/test_dtl.py").write_text("tampered\n")
    (candidate / "Dockerfile").write_text("discarded\n")
    (candidate / "src/coworld/adapter.py").write_text("valid adapter\n")
    output, result = patch(sync, world, meta, candidate)
    assert result.protected_edits == ["tests/test_dtl.py"]
    assert result.dropped_edits == ["Dockerfile", "tests/test_dtl.py"]
    assert b"tampered" not in (output / "candidate.patch").read_bytes()
    notes = json.loads((output / "report-notes.json").read_text())
    assert notes["forced_classification"] == "needs-design"
    assert notes["cause"] == "protected-path-edit"


def test_prepare_survives_expired_report_artifact(sync, world):
    head = add_pr(sync, world, {"src/coworld/prior.py": "prior\n"})
    questions = [{"id": "new-trait", "question": "Should players see this trait?"}]
    world.set_prs([world.pr(head=head, body=pr_state(sync, world, head, questions))])
    _, _, output, result = prepare(sync, world, previous_report=world.path / "expired-report.json")
    assert result["outcome"] == "ready"
    notes = json.loads((output / "context-notes.json").read_text())
    assert notes["open_questions"] == questions
    assert "unavailable" in notes["previous_report"]


def test_patch_reconstructs_exact_tree_from_main(sync, world):
    meta, candidate, _, _ = prepare(sync, world)
    (candidate / "src/coworld/adapter.py").write_text("updated\n")
    output, artifact = patch(sync, world, meta, candidate)
    runner = sync.CommandRunner(env=world.env)
    env = {"GIT_INDEX_FILE": str(world.path / "reconstructed-index")}
    sync._git(runner, candidate, "read-tree", meta.main_sha, env=env)
    sync._git(runner, candidate, "apply", "--cached", "--check", str(output / "candidate.patch"), env=env)
    sync._git(runner, candidate, "apply", "--cached", str(output / "candidate.patch"), env=env)
    sync._git(runner, candidate, "update-index", "--cacheinfo", f"160000,{meta.target_sha},src/sugarscape", env=env)
    assert sync._git(runner, candidate, "write-tree", env=env).stdout.strip() == artifact.candidate_tree


def test_prepare_cli_supports_inputs_and_patch(sync, world):
    import sys
    from dtl_sync_support import ROOT
    meta = world.detect(sync)
    path = world.path / "meta.json"
    sync.write_meta(path, meta)
    candidate = world.path / "cli-candidate"
    env = {**world.env, "GIT_CONFIG_COUNT": "1",
           "GIT_CONFIG_KEY_0": f"url.{world.upstream_remote}.insteadOf",
           "GIT_CONFIG_VALUE_0": sync.UPSTREAM_URL}
    common = [sys.executable, str(ROOT / "tools/dtl_sync.py"), "prepare"]
    inputs = subprocess.run(common + ["inputs", "--meta", str(path), "--directory", str(candidate),
                            "--output", str(world.path / "cli-inputs"), "--checkout", str(world.parent),
                            "--app-login", "dtl-sync[bot]"], env=env, capture_output=True, text=True)
    assert inputs.returncode == 0, inputs.stderr
    assert inputs.stdout == "ready\n"
    patch_result = subprocess.run(common + ["patch", "--meta", str(path), "--directory", str(candidate),
                                 "--output", str(world.path / "cli-patch")], env=env, capture_output=True, text=True)
    assert patch_result.returncode == 0, patch_result.stderr
    data = json.loads((world.path / "cli-patch/candidate.json").read_text())
    assert patch_result.stdout.strip() == data["candidate_tree"]


def test_prepare_rejects_read_only_resume_and_protected_human_edits(sync, world):
    head = add_pr(sync, world, {"tools/dtl_sync.py": "human tool change\n"})
    world.set_prs([world.pr(head=head, body=pr_state(sync, world, world.main))])
    comment = {"body": f"resume-sync {head}", "user": {"login": "reader"},
               "issue_url": "https://api.github.com/repos/owner/game/issues/7"}
    world.api_responses({"repos/owner/game/issues/comments/99": comment,
                         "repos/owner/game/collaborators/reader/permission": {"permission": "read"}})
    _, _, _, result = prepare(sync, world, resume_comment_id=99)
    assert result["outcome"] == "needs-human"
    world.api_responses({"repos/owner/game/issues/comments/99": comment,
                         "repos/owner/game/collaborators/reader/permission": {"permission": "write"}})
    _, _, _, result = prepare(sync, world, resume_comment_id=99)
    assert result["outcome"] == "needs-human"
    assert "protected" in result["reason"]


def test_patch_renames_are_validated_as_delete_and_add(sync, world):
    meta, candidate, _, _ = prepare(sync, world)
    (candidate / "src/coworld/adapter.py").rename(candidate / "src/coworld/renamed.py")
    output, result = patch(sync, world, meta, candidate)
    assert result.files_changed == ["src/coworld/adapter.py", "src/coworld/renamed.py"]
    assert "rename from" not in (output / "candidate.patch").read_text()


def test_patch_records_clean_wrong_upstream_head(sync, world):
    meta, candidate, _, _ = prepare(sync, world)
    git(candidate / "src/sugarscape", "checkout", "--detach", world.first)
    _, result = patch(sync, world, meta, candidate)
    assert "src/sugarscape" in result.protected_edits
    assert git(candidate, "ls-tree", result.candidate_tree, "src/sugarscape").split()[2] == meta.target_sha


def test_patch_rejects_binary_despite_candidate_attributes(sync, world):
    meta, candidate, _, _ = prepare(sync, world)
    (candidate / ".gitattributes").write_text("* diff\n")
    (candidate / "tools/binary").write_bytes(b"\x00invalid")
    with pytest.raises(sync.SyncError, match="binary"):
        patch(sync, world, meta, candidate)


def test_patch_preserves_unchanged_archival_symlinks(sync, world):
    link = world.parent / "archived/v1/.codex/skills"
    link.parent.mkdir(parents=True)
    link.symlink_to("../.agent/skills")
    git(world.parent, "add", "archived")
    git(world.parent, "commit", "-m", "Preserve archive link")
    git(world.parent, "push", "origin", "main")
    meta, candidate, _, _ = prepare(sync, world)
    _, result = patch(sync, world, meta, candidate)
    assert result.dropped_edits == []
    assert git(candidate, "ls-tree", result.candidate_tree, "archived/v1/.codex/skills").startswith("120000 ")
