#!/usr/bin/env python3
"""Publish the GitHub release for the number in VERSION: a draft first, with its files attached, then published.

    python scripts/publish_release.py --target COMMIT [--move-major-tag] FILE [FILE ...]

The release is for the tag `v` plus the VERSION number (v1.6.0), and its title and notes come from
.github/release-notes/vX.Y.Z.md: the first line is the title and starts with the tag (for example
"v1.6.0 - Short title"), then a blank line, then the notes. Each FILE is attached to the release.

The order is the point. An immutable release cannot get files after it is published, so this creates the
release as a draft with the files attached, and publishes it only then. GitHub creates the tag, on COMMIT,
when the draft is published. With --move-major-tag the tag v1 (for 1.x.y) is then moved to COMMIT and pushed.

It changes nothing if the release is already published: a published release is never replaced. A draft
that an earlier run left behind is deleted and created again.

It needs the gh CLI signed in (GH_TOKEN in a workflow), and GITHUB_REPOSITORY (OWNER/REPO), which a workflow sets.
"""
import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def fail(message):
    print(f"publish_release.py: {message}", file=sys.stderr)
    raise SystemExit(1)


def run(*command):
    """Run a command and return its output; stop with its error text if it fails."""
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        fail(f"{' '.join(command[:3])} failed (status {result.returncode}): {result.stderr.strip() or result.stdout.strip()}")
    return result.stdout


def read_version():
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        fail(f"VERSION must hold a number such as 1.6.0, not {version!r}")
    return version


def read_notes(tag):
    """Return (title, notes) from .github/release-notes/TAG.md."""
    path = ROOT / ".github" / "release-notes" / f"{tag}.md"
    if not path.is_file():
        fail(f"{path.relative_to(ROOT)} is missing: write the release notes there before releasing")
    first, _, rest = path.read_text(encoding="utf-8").partition("\n")
    title, notes = first.lstrip("#").strip(), rest.strip("\n")
    if not title.startswith(tag) or not notes:
        fail(f"{path.relative_to(ROOT)} must start with a title line that begins with {tag}, then the notes")
    return title, notes + "\n"


def releases_with_tag(repo, tag):
    """Return [(id, is_draft)] for the releases, drafts included, that have this tag."""
    out = run("gh", "api", "--paginate", f"repos/{repo}/releases", "--jq", ".[] | [.id, .draft, .tag_name] | @tsv")
    found = []
    for line in out.splitlines():
        release_id, draft, name = line.split("\t")
        if name == tag:
            found.append((release_id, draft == "true"))
    return found


def main(argv=None):
    parser = argparse.ArgumentParser(description="Create a draft release with its files, then publish it.")
    parser.add_argument("--target", required=True, metavar="COMMIT", help="the commit the release (and its tag) is for")
    parser.add_argument("--move-major-tag", action="store_true", help="move the tag v1 (for 1.x.y) to COMMIT afterwards")
    parser.add_argument("files", nargs="+", metavar="FILE", help="a file to attach to the release")
    args = parser.parse_args(argv)

    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
        fail("GITHUB_REPOSITORY must name the repository as OWNER/REPO")
    version = read_version()
    tag = f"v{version}"
    title, notes = read_notes(tag)
    for name in args.files:
        if not Path(name).is_file() or Path(name).stat().st_size == 0:
            fail(f"{name} does not exist or is empty")

    existing = releases_with_tag(repo, tag)
    if any(not draft for _, draft in existing):
        print(f"{tag} is already published, so nothing was changed: a published release is never replaced.")
        return
    for release_id, _ in existing:
        print(f"Deleting the draft of {tag} that an earlier run left behind.")
        run("gh", "api", "-X", "DELETE", f"repos/{repo}/releases/{release_id}")

    with tempfile.TemporaryDirectory() as folder:
        notes_file = Path(folder) / "notes.md"
        notes_file.write_text(notes, encoding="utf-8")
        run("gh", "release", "create", tag, *args.files, "--repo", repo, "--draft", "--target", args.target,
            "--title", title, "--notes-file", str(notes_file))
    drafts = [release_id for release_id, draft in releases_with_tag(repo, tag) if draft]
    if len(drafts) != 1:
        fail(f"expected one draft release for {tag} after creating it, found {len(drafts)}")

    release_id = drafts[0]
    run("gh", "api", "-X", "PATCH", f"repos/{repo}/releases/{release_id}", "-F", "draft=false", "-f", "make_latest=true")
    state = run("gh", "api", f"repos/{repo}/releases/{release_id}", "--jq",
                '[.draft, ([.assets[].name] | sort | join(","))] | @tsv').strip()
    expected = ",".join(sorted(Path(name).name for name in args.files))
    if state != f"false\t{expected}":
        fail(f"the published release of {tag} is not as expected (draft and files: {state!r}; wanted false and {expected})")
    print(f"Published {tag} with {expected.replace(',', ', ')}.")

    if args.move_major_tag:
        major = f"v{version.split('.')[0]}"
        run("git", "tag", "-f", major, args.target)
        run("git", "push", "--force", "origin", f"refs/tags/{major}")
        print(f"Moved {major} to {args.target}.")


if __name__ == "__main__":
    main()
