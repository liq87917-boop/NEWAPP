from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from common import ROOT, config, git, run


def _settings() -> dict[str, Any]:
    return config()["github_relay"]


def _gh() -> str | None:
    found = shutil.which("gh")
    if found:
        return found
    candidate = Path(r"C:\Program Files\GitHub CLI\gh.exe")
    return str(candidate) if candidate.exists() else None


def _checked(command: list[str], message: str) -> str:
    result = run(command)
    if result.returncode != 0:
        raise RuntimeError(f"{message}: {(result.stderr or result.stdout).strip()}")
    return result.stdout.strip()


def preflight() -> dict[str, Any]:
    settings = _settings()
    blockers: list[str] = []
    remote = settings["remote"]
    remote_result = git(["remote", "get-url", remote])
    actual_url = remote_result.stdout.strip() if remote_result.returncode == 0 else None
    if actual_url != settings["remote_url"]:
        blockers.append(f"Git remote {remote} is missing or unexpected")
    gh = _gh()
    authenticated = False
    private = False
    if not gh:
        blockers.append("GitHub CLI is unavailable")
    else:
        auth = run([gh, "auth", "status", "--hostname", "github.com"])
        authenticated = auth.returncode == 0
        if not authenticated:
            blockers.append("GitHub CLI is not authenticated")
        else:
            view = run([gh, "repo", "view", settings["repository"], "--json", "isPrivate,nameWithOwner,url"])
            if view.returncode != 0:
                blockers.append("GitHub repository cannot be read")
            else:
                metadata = json.loads(view.stdout)
                private = bool(metadata.get("isPrivate"))
                if metadata.get("nameWithOwner") != settings["repository"]:
                    blockers.append("GitHub repository identity mismatch")
                if settings.get("require_private") and not private:
                    blockers.append("GitHub relay repository is not private")
    return {
        "status": "ready" if not blockers else "blocked",
        "repository": settings["repository"],
        "remote_url": actual_url,
        "authenticated": authenticated,
        "private": private,
        "blockers": blockers,
    }


def ensure_ready() -> None:
    result = preflight()
    if result["blockers"]:
        raise RuntimeError("; ".join(result["blockers"]))


def current_branch() -> str:
    return _checked(["git", "branch", "--show-current"], "Cannot read current branch")


def publish_control_update(message: str, paths: list[str]) -> dict[str, Any]:
    ensure_ready()
    settings = _settings()
    if current_branch() != settings["base_branch"]:
        raise RuntimeError("Control decisions must be published from the main branch")
    _checked(["git", "add", "--", *paths], "Cannot stage control decision")
    staged = git(["diff", "--cached", "--quiet"])
    if staged.returncode == 1:
        _checked(["git", "commit", "-m", message], "Cannot commit control decision")
    _checked(["git", "push", settings["remote"], settings["base_branch"]], "Cannot push control decision")
    return {"status": "published", "branch": settings["base_branch"]}


def prepare_task_branch(task_id: str, run_id: str) -> str:
    ensure_ready()
    settings = _settings()
    if current_branch() != settings["base_branch"]:
        raise RuntimeError("Task execution must start from the main branch")
    if git(["status", "--porcelain"]).stdout.strip():
        raise RuntimeError("Working tree must be clean before creating a task branch")
    _checked(["git", "fetch", settings["remote"], settings["base_branch"]], "Cannot fetch GitHub main")
    _checked(["git", "pull", "--ff-only", settings["remote"], settings["base_branch"]], "Cannot fast-forward main")
    branch = f"{settings['branch_prefix']}{task_id.lower()}-{run_id[-8:]}"
    _checked(["git", "switch", "-c", branch], "Cannot create task branch")
    return branch


def publish_candidate(task: dict[str, Any], run_id: str, branch: str, paths: list[str], manifest_path: str, review_request: str) -> dict[str, Any]:
    ensure_ready()
    settings = _settings()
    if current_branch() != branch:
        raise RuntimeError("Current branch does not match the task branch")
    ordinary = sorted(set(paths + [".ai/project_state.json", ".ai/audit.jsonl", review_request]))
    _checked(["git", "add", "--", *ordinary], "Cannot stage task candidate")
    _checked(["git", "add", "-f", "--", manifest_path], "Cannot stage evidence manifest")
    if git(["diff", "--cached", "--quiet"]).returncode == 0:
        raise RuntimeError("Task produced no publishable changes")
    _checked(["git", "commit", "-m", f"{task['id']}: candidate for GPT review"], "Cannot commit task candidate")
    _checked(["git", "push", "-u", settings["remote"], branch], "Cannot push task branch")
    gh = _gh()
    body = "\n".join([
        f"Task: {task['id']}",
        f"Run: {run_id}",
        f"Evidence: `{manifest_path}`",
        "",
        "Cline/DeepSeek produced this candidate. GPT acceptance is required before merge."
    ])
    url = _checked([str(gh), "pr", "create", "--repo", settings["repository"], "--base", settings["base_branch"], "--head", branch, "--title", f"{task['id']}: {task.get('title', 'candidate')}", "--body", body], "Cannot create GitHub pull request")
    return {"status": "published", "branch": branch, "pr_url": url.strip()}


def publish_branch_metadata(message: str, paths: list[str], branch: str) -> None:
    settings = _settings()
    if current_branch() != branch:
        raise RuntimeError("Current branch does not match metadata branch")
    _checked(["git", "add", "--", *paths], "Cannot stage branch metadata")
    if git(["diff", "--cached", "--quiet"]).returncode == 1:
        _checked(["git", "commit", "-m", message], "Cannot commit branch metadata")
        _checked(["git", "push", settings["remote"], branch], "Cannot push branch metadata")


def finalize_review(task_id: str, branch: str, decision: str, paths: list[str], rationale: str) -> dict[str, Any]:
    ensure_ready()
    settings = _settings()
    gh = _gh()
    publish_branch_metadata(f"{task_id}: GPT {decision}", paths, branch)
    _checked([str(gh), "pr", "comment", branch, "--repo", settings["repository"], "--body", f"GPT decision: **{decision}**\n\n{rationale}"], "Cannot publish GPT review comment")
    if decision != "accept":
        return {"status": "review_recorded", "branch": branch, "merged": False}
    pr_number = _checked([str(gh), "pr", "view", branch, "--repo", settings["repository"], "--json", "number", "--jq", ".number"], "Cannot resolve pull request")
    _checked([str(gh), "pr", "merge", pr_number, "--repo", settings["repository"], f"--{settings['merge_method']}", "--delete-branch"], "Cannot merge accepted pull request")
    _checked(["git", "switch", settings["base_branch"]], "Cannot return to main")
    _checked(["git", "pull", "--ff-only", settings["remote"], settings["base_branch"]], "Cannot refresh merged main")
    return {"status": "merged", "branch": branch, "merged": True, "pr_number": int(pr_number)}
