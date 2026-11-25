"""Tests for scripts/publish_release.py, with a fake `gh` that keeps its releases in a file."""
import json
import shutil
import sys
from pathlib import Path

from gitutil import sh

ROOT = Path(__file__).resolve().parent.parent
REPO = "owner/repo"

FAKE_GH = """import json, sys
state_path = {state!r}
args = sys.argv[1:]
if args == ["--version"]:
    print("fake gh")
    sys.exit(0)
state = json.load(open(state_path))
state["log"].append(args[0] + (" " + args[2] if args[:2] == ["api", "-X"] else ""))
if args[:2] == ["api", "--paginate"]:
    for r in state["releases"]:
        print("\\t".join([str(r["id"]), "true" if r["draft"] else "false", r["tag"]]))
elif args[:3] == ["api", "-X", "DELETE"]:
    state["releases"] = [r for r in state["releases"] if str(r["id"]) != args[3].rsplit("/", 1)[1]]
elif args[:3] == ["api", "-X", "PATCH"]:
    for r in state["releases"]:
        if str(r["id"]) == args[3].rsplit("/", 1)[1]:
            assert "draft=false" in args
            r["draft"] = False
elif args[0] == "api":
    for r in state["releases"]:
        if str(r["id"]) == args[1].rsplit("/", 1)[1]:
            print("\\t".join(["true" if r["draft"] else "false", ",".join(sorted(r["assets"]))]))
elif args[:2] == ["release", "create"]:
    files = []
    for a in args[3:]:
        if a.startswith("--"):
            break
        files.append(a)
    notes = open(args[args.index("--notes-file") + 1]).read()
    state["releases"].append({{"id": 100 + len(state["releases"]), "tag": args[2], "draft": "--draft" in args,
        "assets": [f.rsplit("/", 1)[-1] for f in files], "title": args[args.index("--title") + 1],
        "target": args[args.index("--target") + 1], "notes": notes}})
json.dump(state, open(state_path, "w"))
"""


def setup(tmp_path, notes="v1.6.0 - Short title\n\nWhat changed.\n", version="1.6.0", releases=()):
    """A copy of the script in a fake repository root, a fake gh on PATH, and a git repo with a bare origin."""
    root = tmp_path / "root"
    (root / "scripts").mkdir(parents=True)
    (root / ".github" / "release-notes").mkdir(parents=True)
    shutil.copy(ROOT / "scripts" / "publish_release.py", root / "scripts")
    (root / "VERSION").write_text(version + "\n", encoding="utf-8")
    if notes is not None:
        (root / ".github" / "release-notes" / "v1.6.0.md").write_text(notes, encoding="utf-8")
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"releases": list(releases), "log": []}), encoding="utf-8")
    fake = tmp_path / "bin"
    fake.mkdir()
    (tmp_path / "fake_gh.py").write_text(FAKE_GH.format(state=str(state)), encoding="utf-8")
    # A shell wrapper, because the path of this Python can contain spaces, and a #! line cannot.
    (fake / "gh").write_text(f'#!/bin/sh\nexec "{sys.executable}" "{tmp_path / "fake_gh.py"}" "$@"\n', encoding="utf-8")
    (fake / "gh").chmod(0o755)
    files = []
    for name in ("bootstrap.sh", "bootstrap.sh.sha256"):
        (tmp_path / name).write_text("content\n", encoding="utf-8")
        files.append(str(tmp_path / name))
    origin, work = tmp_path / "origin.git", tmp_path / "work"
    git = {"HOME": str(tmp_path), "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e.com",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@e.com"}
    sh(["git", "init", "--quiet", "--bare", str(origin)], env=git)
    sh(["git", "init", "--quiet", str(work)], env=git)
    sh(["git", "-C", str(work), "remote", "add", "origin", str(origin)], env=git)
    sh(["git", "-C", str(work), "commit", "--quiet", "--allow-empty", "-m", "x"], env=git)
    commit = sh(["git", "-C", str(work), "rev-parse", "HEAD"], env=git).stdout.strip()
    env = {**git, "PATH": f"{fake}:" + sh(["bash", "-c", "echo $PATH"]).stdout.strip(), "GITHUB_REPOSITORY": REPO}
    # If the fake cannot run, the search for `gh` moves on to a real one, so make sure that it is the fake.
    version = sh(["gh", "--version"], env=env, check=False)
    assert version.stdout.strip() == "fake gh", f"the fake gh is not the gh that runs: {version.stdout}{version.stderr}"
    return root, work, origin, state, files, commit, env


def publish(root, work, files, commit, env, *extra):
    return sh([sys.executable, str(root / "scripts" / "publish_release.py"), "--target", commit, *extra, *files],
              cwd=work, env=env, check=False)


def tags(origin, env):
    return sh(["git", "ls-remote", "--tags", str(origin)], env=env).stdout.split()


def test_it_creates_a_draft_with_the_files_and_only_then_publishes(tmp_path):
    root, work, origin, state, files, commit, env = setup(tmp_path)
    done = publish(root, work, files, commit, env)
    assert done.returncode == 0, done.stderr
    data = json.loads(state.read_text(encoding="utf-8"))
    (release,) = data["releases"]
    assert release["draft"] is False and release["tag"] == "v1.6.0" and release["target"] == commit
    assert release["title"] == "v1.6.0 - Short title" and release["notes"] == "What changed.\n"
    assert release["assets"] == ["bootstrap.sh", "bootstrap.sh.sha256"]
    assert [line for line in data["log"] if line in ("release", "api PATCH")] == ["release", "api PATCH"]


def test_no_tag_is_pushed_unless_asked(tmp_path):
    root, work, origin, state, files, commit, env = setup(tmp_path)
    assert publish(root, work, files, commit, env).returncode == 0
    assert tags(origin, env) == []


def test_the_major_tag_moves_after_a_new_release(tmp_path):
    root, work, origin, state, files, commit, env = setup(tmp_path)
    done = publish(root, work, files, commit, env, "--move-major-tag")
    assert done.returncode == 0, done.stderr
    assert tags(origin, env) == [commit, "refs/tags/v1"]


def test_a_published_release_is_never_replaced(tmp_path):
    """Not even when a run asks for the major tag: nothing is created, deleted, published or pushed."""
    published = {"id": 7, "tag": "v1.6.0", "draft": False, "assets": ["bootstrap.sh"], "title": "old", "target": "x", "notes": "old\n"}
    root, work, origin, state, files, commit, env = setup(tmp_path, releases=[published])
    done = publish(root, work, files, commit, env, "--move-major-tag")
    assert done.returncode == 0 and "already published" in done.stdout
    assert tags(origin, env) == []
    data = json.loads(state.read_text(encoding="utf-8"))
    assert data["releases"] == [published]
    assert not any(line in ("release", "api PATCH", "api DELETE") for line in data["log"])


def test_a_draft_left_by_an_earlier_run_is_replaced(tmp_path):
    stale = {"id": 7, "tag": "v1.6.0", "draft": True, "assets": [], "title": "stale", "target": "x", "notes": "stale\n"}
    other = {"id": 8, "tag": "v1.5.0", "draft": False, "assets": [], "title": "other", "target": "y", "notes": "other\n"}
    root, work, origin, state, files, commit, env = setup(tmp_path, releases=[stale, other])
    done = publish(root, work, files, commit, env)
    assert done.returncode == 0, done.stderr
    data = json.loads(state.read_text(encoding="utf-8"))
    assert [(r["tag"], r["draft"]) for r in data["releases"]] == [("v1.5.0", False), ("v1.6.0", False)]


def test_it_stops_before_touching_anything_when_the_notes_or_files_are_wrong(tmp_path):
    for case, notes in (("missing", None), ("wrong-title", "v1.5.0 - Old\n\nText.\n"), ("no-notes", "v1.6.0 - Title\n")):
        folder = tmp_path / case
        folder.mkdir()
        root, work, origin, state, files, commit, env = setup(folder, notes=notes)
        assert publish(root, work, files, commit, env).returncode == 1, case
        assert json.loads(state.read_text(encoding="utf-8"))["log"] == [], case
    folder = tmp_path / "file"
    folder.mkdir()
    root, work, origin, state, files, commit, env = setup(folder)
    done = publish(root, work, [files[0], str(folder / "missing")], commit, env)
    assert done.returncode == 1 and "does not exist or is empty" in done.stderr
    assert json.loads(state.read_text(encoding="utf-8"))["log"] == []


def test_a_version_that_is_not_a_plain_number_is_refused(tmp_path):
    root, work, origin, state, files, commit, env = setup(tmp_path, version="1.6.0-rc1")
    done = publish(root, work, files, commit, env)
    assert done.returncode == 1 and "VERSION must hold a number" in done.stderr
