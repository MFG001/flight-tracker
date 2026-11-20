#!/usr/bin/env python3
"""Stage the public repo as ONE fresh commit in a separate folder. Never pushes.

  python3 scripts/stage_public.py /path/to/empty-or-missing-folder --message "Flight Tracker 1.0.7"

Copies the files git would publish (tracked + untracked, minus .gitignore'd),
leaves out screenshots no doc or script uses, makes a brand-new repository with
a single commit by the neutral author below (no history, no remote), then runs
scripts/scrub_check.py on the staged tree and its commit metadata. Exit 1 if
anything personal is found.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import scrub_check  # noqa: E402

AUTHOR_NAME = "Maverick Field Gear"
AUTHOR_EMAIL = "340321607+MFG001@users.noreply.github.com"


def used_screenshots(files: list[Path]) -> set[str]:
    names: set[str] = {"config-desktop.png"}
    for path in files:
        if path.suffix in (".md", ".mjs", ".py", ".html", ".ts", ".sh") and "screenshots" not in path.parts:
            names |= set(re.findall(r"docs/screenshots/([A-Za-z0-9_-]+\.png)", path.read_text(errors="ignore")))
    return names


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dest")
    parser.add_argument("--message", default="Flight Tracker by Maverick Field Gear")
    args = parser.parse_args()
    dest = Path(args.dest).resolve()
    if dest.exists() and any(dest.iterdir()):
        raise SystemExit(f"{dest} must be empty or missing")
    files = scrub_check.publish_files(ROOT)
    keep_shots = used_screenshots(files)
    dropped = []
    dest.mkdir(parents=True, exist_ok=True)
    for path in files:
        rel = path.relative_to(ROOT)
        if rel.parts[:2] == ("docs", "screenshots") and rel.name not in keep_shots:
            dropped.append(str(rel))
            continue
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    env = dict(os.environ, GIT_AUTHOR_NAME=AUTHOR_NAME, GIT_AUTHOR_EMAIL=AUTHOR_EMAIL,
               GIT_COMMITTER_NAME=AUTHOR_NAME, GIT_COMMITTER_EMAIL=AUTHOR_EMAIL)
    git = lambda *a: subprocess.run(["git", "-c", "init.defaultBranch=main", "-c", f"user.name={AUTHOR_NAME}",
                                     "-c", f"user.email={AUTHOR_EMAIL}", "-c", "commit.gpgsign=false", *a],
                                    cwd=dest, env=env, check=True, capture_output=True, text=True)
    git("init", "-q")
    git("add", "-A")
    git("commit", "-q", "-m", args.message)
    print(f"Staged {len(files) - len(dropped)} files in one commit at {dest} (no remote).")
    print(f"Left out {len(dropped)} unused screenshots.")
    found = scrub_check.scan_tree(dest, frozenset()) + scrub_check.scan_git_log(dest, frozenset())
    if found:
        print("Personal data found:\n  " + "\n  ".join(found), file=sys.stderr)
        return 1
    print("Scrub check passed on the staged tree and its commit metadata.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
