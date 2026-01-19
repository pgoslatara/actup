import json
import os
import re
import shutil
from pathlib import Path

import ollama
import yaml
from git import Repo

from actup.config import settings
from actup.logger import logger


def deduplicate_list(input_list):
    """Deduplicate a list of elements."""
    seen = set()
    deduplicated_list = []
    for item in input_list:
        if isinstance(item, (list, dict, set)) and not isinstance(item, frozenset):
            deduplicated_list.append(item)
        elif item not in seen:
            seen.add(item)
            deduplicated_list.append(item)
    return deduplicated_list


def git_clone_shallow(repo_url: str, target_dir: str):
    """Clone a git repository shallowly."""
    if Path(target_dir).exists():
        shutil.rmtree(target_dir)

    os.makedirs(target_dir, exist_ok=True)
    return Repo.clone_from(repo_url, target_dir, depth=1)


def git_clone_sparse(repo_url: str, final_target_dir: str):
    """Clones a Git repository using sparse checkout."""
    repo_root_path = Path(final_target_dir)

    if repo_root_path.exists():
        shutil.rmtree(repo_root_path)

    os.makedirs(repo_root_path, exist_ok=True)
    repo = Repo.init(repo_root_path)
    origin = repo.create_remote("origin", repo_url)
    repo.config_writer().set_value("core", "sparseCheckout", True).release()
    sparse_checkout_file = repo_root_path / ".git" / "info" / "sparse-checkout"
    with open(sparse_checkout_file, "w") as f:
        f.write("/.github/\n")
    origin.fetch(depth=1)
    try:
        repo.git.checkout("main")
    except Exception:
        try:
            repo.git.checkout("master")
        except Exception:
            try:
                repo.git.checkout("develop")
            except Exception:
                logger.warning(f"Unable to checkout {repo_url}")


def is_major_version_outdated(detected_version: str, latest_version: str) -> bool:
    """Check if the detected version is older than the latest version."""
    if not detected_version or not latest_version:
        return False

    if isinstance(detected_version, int):
        detected_version = str(detected_version)
    if isinstance(latest_version, int):
        latest_version = str(latest_version)

    try:
        detected_major = int(detected_version.lstrip("v").split(".")[0])
        latest_major = int(latest_version.lstrip("v").split(".")[0])
        return detected_major < latest_major
    except ValueError:
        return False


def load_ollama_model(model_name: str) -> None:
    """Load the Ollama model, If not already present, download it."""
    logger.debug(f"Attempting to pull model: {model_name}. This may take a while if not cached.")
    pull_response = ollama.pull(model_name, stream=True)
    for chunk in pull_response:
        if "status" in chunk:
            logger.debug(f"Pull Status: {chunk['status']}")


def merge_pr_body_into_template(pr_body: str, pull_request_template_body: str) -> str:
    """Ue Ollama to populate the PR template."""
    model_name = "qwen3:1.7b"
    prompt = f"""
    You are a software engineer who is updating the version of actions used in GitHub Action workflows. You are creating a pull request in an open source GitHub repository that has a pull request template. Your job is to merge this template with the description of your changes. Return a markdown formatted response that correctly fills in the pull request template as best you can while at the same time correctly describing your changes.

    Here is the pull request template:
    {pull_request_template_body}

    Here are the changes you want to make:
    {pr_body}

    Constraints:
    * Do not return anything that isn't markdown formatted.
    * Do not make up information.
    * Do not alter the format of the pull request template.
    * If you need to specify how the changes will be tested, state that they will be tested in the CI pipeline of the pull request.
    * If you see boxes like this "[ ]", then fill them in like "[x]" if they are completed (for example, having an accurate PR title, detailing the changes in the PR description, etc.).
    * Do not return a response with "```markdown" at the start.
    """  # noqa: E501

    load_ollama_model(model_name=model_name)
    logger.info("Sending request to Ollama...")
    response = ollama.generate(
        model=model_name,
        options={
            "format": "json",
        },
        prompt=prompt,
        stream=False,
    ).response
    logger.info("Response received from Ollama...")
    return response


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


def scan_file_for_action_line_number(file_content: str, action: str) -> list[tuple[int, str, str]]:
    """Identify the line number in a file where an action is used."""
    results = []
    lines = file_content.splitlines()
    for i, line in enumerate(lines):
        parsed = parse_action_version(line)
        if parsed:
            name, version = parsed
            if name == action:
                results.append((i + 1, name, version))
    return results


def search_and_extract_actions(repo_data):
    """Search files for GitHub Actions and extract the used actions."""
    repo_full_name = repo_data.repo_full_name
    repo_dir = Path(settings.temp_dir) / "cloned_repos" / repo_full_name.replace("/", "_")
    used_actions = []

    if not os.path.exists(repo_dir):
        logger.error(f"Directory {repo_dir} does not exist.")
        return

    for dirpath, _, filenames in os.walk(repo_dir):
        for filename in filenames:
            if filename.endswith((".yml", ".yaml")):
                filepath = os.path.join(dirpath, filename)

                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        try:
                            content_yaml = yaml.safe_load(f)
                        except yaml.YAMLError:
                            continue

                    if not isinstance(content_yaml, dict):
                        continue

                    # GitHub Actions workflows typically have a 'jobs' key
                    if "jobs" in content_yaml and isinstance(content_yaml["jobs"], dict):
                        with open(filepath, "r", encoding="utf-8") as f:
                            content_raw = f.read()

                        for _, job in content_yaml["jobs"].items():
                            if not isinstance(job, dict):
                                continue

                            # Check for reusable workflow invocation
                            if "uses" in job:
                                used_actions.append(
                                    {
                                        "action_raw": job["uses"],
                                        "filepath": filepath,
                                        "line_numbers": scan_file_for_action_line_number(
                                            file_content=content_raw, action=job["uses"][: job["uses"].find("@")]
                                        ),
                                    }
                                )

                            if "steps" in job and isinstance(job["steps"], list):
                                used_actions.extend(
                                    {
                                        "action_raw": step["uses"],
                                        "filepath": filepath,
                                        "line_numbers": scan_file_for_action_line_number(
                                            file_content=content_raw, action=step["uses"][: step["uses"].find("@")]
                                        ),
                                    }
                                    for step in job["steps"]
                                    if isinstance(step, dict) and "uses" in step
                                )

                except Exception as e:
                    logger.warning(f"Error processing {filepath}: {e}")
                    continue

    used_actions_per_line = []
    for i in used_actions:
        i["repo_full_name"] = repo_full_name
        used_actions_per_line.extend(split_dict_by_line_numbers(i))

    for i in used_actions:
        i["action_name"] = i["line_numbers"][0][1] if i.get("line_numbers") else "Unknown"
        i["action_version"] = i["line_numbers"][0][2] if i.get("line_numbers") else "Unknown"
        i["line_number"] = i["line_numbers"][0][0] if i.get("line_numbers") else -1
        i.pop("line_numbers")

    dir = f"./{settings.temp_dir}/action_usage/{repo_full_name}"
    Path(dir).mkdir(exist_ok=True, parents=True)
    with open(f"{dir}/actions_used.json", "w") as f:
        json.dump(deduplicate_list(used_actions), f)


def split_dict_by_line_numbers(original_dict):
    """Take a dict that has a nested list and return multiple dicts."""
    new_dicts = []
    line_numbers_list = original_dict.get("line_numbers", [])

    # Create a base dictionary with all keys except 'line_numbers'
    base_dict = {k: v for k, v in original_dict.items() if k != "line_numbers"}

    for line_info_tuple in line_numbers_list:
        new_entry = base_dict.copy()
        new_entry["line_numbers"] = line_info_tuple
        new_dicts.append(new_entry)

    return new_dicts
