from __future__ import annotations

from typing import Any

from common import config, git, path_matches


def is_repository() -> bool:
    return git(["rev-parse", "--is-inside-work-tree"]).returncode == 0


def has_head() -> bool:
    return is_repository() and git(["rev-parse", "--verify", "HEAD"]).returncode == 0


def changed_paths() -> list[str]:
    if not is_repository():
        return []
    result = git(["status", "--porcelain=v1", "--untracked-files=all"])
    paths: list[str] = []
    for line in result.stdout.splitlines():
        raw = line[3:].strip()
        if " -> " in raw:
            raw = raw.split(" -> ", 1)[1]
        paths.append(raw.strip('"').replace("\\", "/"))
    return paths


def guard_changes(before: set[str], allowed_paths: list[str]) -> dict[str, Any]:
    cfg = config()["paths"]
    current = set(changed_paths())
    new_or_changed = sorted(current - before)
    protected = [path for path in new_or_changed if path_matches(path, cfg["protected"])]
    outside = [path for path in new_or_changed if not path_matches(path, allowed_paths)]
    return {"status": "passed" if not protected and not outside else "failed", "changed_paths": new_or_changed, "protected_paths": protected, "outside_allowed_paths": outside}


def checkpoint(task_id: str, title: str, paths: list[str]) -> dict[str, Any]:
    if not is_repository() or not has_head():
        return {"status": "skipped", "reason": "Git repository has no baseline commit"}
    safe_paths = [path for path in paths if path and not path_matches(path, config()["paths"]["protected"])]
    if not safe_paths:
        return {"status": "skipped", "reason": "No safe task paths to commit"}
    add = git(["add", "--", *safe_paths])
    if add.returncode != 0:
        return {"status": "failed", "reason": add.stderr.strip()}
    if git(["diff", "--cached", "--quiet"]).returncode == 0:
        return {"status": "skipped", "reason": "No staged changes"}
    commit = git(["commit", "-m", f"{task_id}: {title}"])
    return {"status": "committed" if commit.returncode == 0 else "failed", "output": (commit.stdout + commit.stderr).strip()}

