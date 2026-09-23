from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import quote

from common import ROOT, config, git, run


def _settings() -> dict[str, Any]:
    return config()["github_relay"]


def _checked(command: list[str], message: str) -> str:
    result = run(command)
    if result.returncode != 0:
        raise RuntimeError(f"{message}: {(result.stderr or result.stdout).strip()}")
    return result.stdout.strip()


def _repo_web_url() -> str:
    repository = str(_settings()["repository"])
    return f"https://github.com/{repository}"


def preflight() -> dict[str, Any]:
    """Validate the relay using Git itself.

    NEWAPP intentionally does not require GitHub CLI authentication. The local
    automation only needs authenticated Git fetch/push access. GPT can inspect
    the pushed branch through the connected GitHub integration.
    """
    settings = _settings()
    blockers: list[str] = []
    remote = str(settings["remote"])
    remote_result = git(["remote", "get-url", remote])
    actual_url = remote_result.stdout.strip() if remote_result.returncode == 0 else None
    if actual_url != settings["remote_url"]:
        blockers.append(f"Git remote {remote} is missing or unexpected")

    reachable = False
    if actual_url:
        probe = git(["ls-remote", "--exit-code", remote, f"refs/heads/{settings['base_branch']}"])
        reachable = probe.returncode == 0 and bool(probe.stdout.strip())
        if not reachable:
            detail = (probe.stderr or probe.stdout).strip()
            blockers.append(
                "GitHub repository cannot be reached through the configured Git remote"
                + (f": {detail}" if detail else "")
            )

    return {
        "status": "ready" if not blockers else "blocked",
        "repository": settings["repository"],
        "remote_url": actual_url,
        "git_authenticated": reachable,
        "transport": "git_ssh",
        "github_cli_required": False,
        "private": True if settings.get("require_private") else None,
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


def publish_candidate(
    task: dict[str, Any],
    run_id: str,
    branch: str,
    paths: list[str],
    manifest_path: str,
    review_request: str,
) -> dict[str, Any]:
    """Publish a candidate branch without requiring gh/PR creation."""
    ensure_ready()
    settings = _settings()
    if current_branch() != branch:
        raise RuntimeError("Current branch does not match the task branch")
    ordinary = sorted(set(paths + [review_request]))
    _checked(["git", "add", "--", *ordinary], "Cannot stage task candidate")
    _checked(["git", "add", "-f", "--", manifest_path], "Cannot stage evidence manifest")
    if git(["diff", "--cached", "--quiet"]).returncode == 0:
        raise RuntimeError("Task produced no publishable changes")
    _checked(["git", "commit", "-m", f"{task['id']}: candidate for GPT review"], "Cannot commit task candidate")
    _checked(["git", "push", "-u", settings["remote"], branch], "Cannot push task branch")
    # Runtime state/audit belong to main in rolling mode; do not merge branch-local
    # snapshots back later and overwrite newer queue/review information.
    git(["restore", "--", ".ai/project_state.json", ".ai/audit.jsonl"])
    encoded_branch = quote(branch, safe="/-_.")
    review_url = f"{_repo_web_url()}/tree/{encoded_branch}"
    return {
        "status": "published",
        "branch": branch,
        "review_url": review_url,
        "pr_url": None,
        "relay_mode": "git_branch",
    }


def return_to_base() -> None:
    settings = _settings()
    base = str(settings["base_branch"])
    remote = str(settings["remote"])
    if git(["status", "--porcelain"]).stdout.strip():
        raise RuntimeError("Cannot return to main with a dirty task branch")
    if current_branch() != base:
        _checked(["git", "switch", base], "Cannot return to main")
    _checked(["git", "fetch", remote, base], "Cannot fetch GitHub main")
    _checked(["git", "pull", "--ff-only", remote, base], "Cannot refresh main")


def refresh_base() -> None:
    settings = _settings()
    base = str(settings["base_branch"])
    remote = str(settings["remote"])
    if current_branch() != base:
        raise RuntimeError("Idle refresh requires the base branch")
    if git(["status", "--porcelain"]).stdout.strip():
        raise RuntimeError("Idle refresh requires a clean working tree")
    _checked(["git", "fetch", remote, base], "Cannot fetch GitHub main")
    _checked(["git", "pull", "--ff-only", remote, base], "Cannot refresh main")


def publish_branch_metadata(message: str, paths: list[str], branch: str) -> None:
    settings = _settings()
    if current_branch() != branch:
        raise RuntimeError("Current branch does not match metadata branch")
    _checked(["git", "add", "--", *paths], "Cannot stage branch metadata")
    if git(["diff", "--cached", "--quiet"]).returncode == 1:
        _checked(["git", "commit", "-m", message], "Cannot commit branch metadata")
        _checked(["git", "push", settings["remote"], branch], "Cannot push branch metadata")


def finalize_review(task_id: str, branch: str, decision: str, paths: list[str], rationale: str) -> dict[str, Any]:
    """Finalize GPT review using Git only.

    Accepted work is squash-merged into main and pushed through the already
    authenticated SSH remote. Rejected work remains on its task branch.
    """
    ensure_ready()
    settings = _settings()
    publish_branch_metadata(f"{task_id}: GPT {decision}", paths, branch)
    if decision != "accept":
        return {
            "status": "review_recorded",
            "branch": branch,
            "merged": False,
            "relay_mode": "git_branch",
        }

    base_branch = str(settings["base_branch"])
    remote = str(settings["remote"])
    _checked(["git", "switch", base_branch], "Cannot return to main")
    _checked(["git", "fetch", remote, base_branch], "Cannot fetch GitHub main")
    _checked(["git", "pull", "--ff-only", remote, base_branch], "Cannot refresh merged main")

    squash = git(["merge", "--squash", branch])
    if squash.returncode != 0:
        git(["merge", "--abort"])
        raise RuntimeError(f"Cannot squash accepted task branch: {(squash.stderr or squash.stdout).strip()}")

    if git(["diff", "--cached", "--quiet"]).returncode == 1:
        _checked(
            ["git", "commit", "-m", f"{task_id}: accepted by GPT"],
            "Cannot commit accepted task",
        )
    _checked(["git", "push", remote, base_branch], "Cannot push accepted task to main")

    # Branch cleanup is best-effort after main is safely pushed.
    git(["push", remote, "--delete", branch])
    git(["branch", "-D", branch])
    return {
        "status": "merged",
        "branch": branch,
        "merged": True,
        "relay_mode": "git_branch",
        "review_url": f"{_repo_web_url()}/commits/{base_branch}",
    }
