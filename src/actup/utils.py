import os
import re
import shutil
from pathlib import Path

from git import Repo


def git_clone_shallow(repo_url: str, target_dir: str):
    """Clone a git repository shallowly."""
    if Path(target_dir).exists():
        shutil.rmtree(target_dir)

    os.makedirs(target_dir, exist_ok=True)
    return Repo.clone_from(repo_url, target_dir, depth=1)


def is_major_version_outdated(detected_version: str, latest_version: str) -> bool:
    """Check if the detected version is older than the latest version."""
    if not detected_version.startswith("v") or not latest_version.startswith("v"):
        return False

    try:
        detected_major = int(detected_version.lstrip("v").split(".")[0])
        latest_major = int(latest_version.lstrip("v").split(".")[0])
        return detected_major < latest_major
    except ValueError:
        return False


def parse_action_version(action_line: str) -> tuple[str, str] | None:
    """Parse the action name and version from a line."""
    pattern = r"uses:\s+([a-zA-Z0-9_\-]+/[a-zA-Z0-9_\-]+)@([a-zA-Z0-9_\-\.]+)"
    match = re.search(pattern, action_line)
    if match:
        return match.group(1), match.group(2)
    return None


def replace_action_version_in_content(content: str, action_name: str, old_version: str, new_version: str) -> str:
    """Replace the action version in the content."""
    pattern = f"uses: {action_name}@{old_version}"
    replacement = f"uses: {action_name}@{new_version}"
    return content.replace(pattern, replacement)


def scan_file_for_actions(file_content: str, action_list: list[str]) -> list[tuple[int, str, str]]:
    """Scan file content for actions in the action list."""
    results = []
    lines = file_content.splitlines()
    for i, line in enumerate(lines):
        parsed = parse_action_version(line)
        if parsed:
            name, version = parsed
            if name in action_list:
                results.append((i + 1, name, version))
    return results
