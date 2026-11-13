"""Test that last_build.json stays readable in one call when the report would be too long."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bites_tool import cli  # noqa: E402

COUNT = 120


def git(cwd, *args):
    """Run git in `cwd` with a fixed identity; raise if it fails."""
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=cwd, check=True, capture_output=True,
    )


def build(tmp_path, src, out, manifest_max):
    """Run `bites build` with tiny parts (max_chars = 10) and the given manifest limit."""
    cfg = tmp_path / "bites.toml"
    cfg.write_text(f"max_chars = 10\nmanifest_max_chars = {manifest_max}\n", encoding="utf-8")
    rc = cli.main([
        "build", "--config", str(cfg), "--src", str(src), "--out", str(out),
        "--source-branch", "t", "--source-commit", "c",
    ])
    assert rc == 0


def test_long_removed_list_is_trimmed_to_fit_one_read(tmp_path):
    src, out = tmp_path / "src", tmp_path / "out"
    src.mkdir()
    git(src, "init", "-q")
    names = [f"f{i:03d}.md" for i in range(COUNT)]
    for n in names:
        (src / n).write_text("x" * 25, encoding="utf-8")
    git(src, "add", "-A")
    git(src, "commit", "-q", "-m", "one")
    build(tmp_path, src, out, 100000)

    git(src, "rm", "-q", "--", *names)
    git(src, "commit", "-q", "-m", "two")
    build(tmp_path, src, out, 1500)

    text = (out / "last_build.json").read_text(encoding="utf-8")
    assert len(text) <= 1500
    report = json.loads(text)
    assert report["status"] == "ok"
    assert report["truncated_report"] is True
    assert report["removed_total"] == COUNT
    assert 0 < len(report["removed"]) < COUNT
