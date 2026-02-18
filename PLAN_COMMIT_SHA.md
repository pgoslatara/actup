# Plan: Add Commit Hash Pinning for GitHub Actions

## Overview
Add functionality to replace action versions with commit SHAs (pinning to exact commits) while keeping a comment with the original version for reference. This provides more reproducible builds.

## Current State
- Actions are identified by version tags (e.g., `actions/checkout@v4.0.1`)
- No commit SHA resolution exists in the codebase
- `PullRequestCreator` class handles PR creation

## Implementation Plan

### Phase 1: Add Commit SHA Resolution to GitHub API Client

**File: `src/actup/github_api.py`**

Add methods:
```python
def get_tag_sha(self, owner: str, repo: str, tag: str) -> str:
    """Resolve a tag to its commit SHA."""

def get_tags(self, owner: str, repo: str) -> list[dict]:
    """Get all tags for a repository."""
```

**GitHub API endpoints:**
- `GET /repos/{owner}/{repo}/tags` - list all tags
- `GET /repos/{owner}/{repo}/git/refs/tags/{tag}` or `GET /repos/{owner}/{repo}/git/tags/{sha}` - resolve tag to commit

### Phase 2: Update Data Models

**File: `src/actup/models.py`**

Add optional `commit_sha` field:
- `GitHubAction` - add `commit_sha: str | None = None`
- `RepositoryMention` - add `commit_sha: str | None = None`

### Phase 3: Update Database Schema

**File: `src/actup/database.py`**

1. Add `commit_sha` column to `popular_actions` table
2. Add `commit_sha` column to `action_mentions` table
3. Update queries to fetch/store commit SHA

### Phase 4: Update CLI Commands

**File: `src/actup/cli.py`**

1. Add `find-action-shas` command - resolves all stored action versions to commit SHAs
2. Add `--pin-to-sha` flag to `create-prs` command

### Phase 5: Refactor PullRequestCreator

**File: `src/actup/pr_creator.py`**

Refactor to support both update modes:

1. Add `UpdateMode` enum:
   ```python
   class UpdateMode(str, Enum):
       LATEST_VERSION = "latest_version"  # Current behavior
       PIN_TO_SHA = "pin_to_sha"          # New behavior
   ```

2. Modify `__init__` to accept update mode:
   ```python
   def __init__(self, client, temp_dir=None, mode=UpdateMode.LATEST_VERSION):
   ```

3. Modify `update_workflow_files()` to support comment injection:
   ```python
   def update_workflow_files(self, mentions, repo_dir, include_comment=True):
       # When pinning to SHA, inject comment:
       # # actions/checkout@v4.0.1 -> actions/checkout@7a...
       # uses: actions/checkout@v4.0.1
       # becomes:
       # # actions/checkout@v4.0.1 -> actions/checkout@7a1234567890abcdef
       # uses: actions/checkout@7a1234567890abcdef
   ```

4. Modify `build_pr_details()` for new PR title/body:
   - When pinning: "chore: Pin GitHub Actions to commit SHAs"
   - Body includes version -> SHA mapping

### Phase 6: Testing

- Add tests for tag-to-SHA resolution
- Add tests for workflow file modification with comments
- Test both update modes work correctly

## File Changes Summary

| File | Changes |
|------|---------|
| `github_api.py` | Add `get_tag_sha()`, `get_tags()` |
| `models.py` | Add `commit_sha` to `GitHubAction`, `RepositoryMention` |
| `database.py` | Add columns, update queries |
| `cli.py` | Add `find-action-shas` command, `--pin-to-sha` flag |
| `pr_creator.py` | Add `UpdateMode` enum, refactor for both modes |

## Usage

```bash
# Update to latest versions (current behavior)
actup create-prs

# Pin actions to commit SHAs (new behavior)
actup create-prs --pin-to-sha
```

## Considerations

1. **Caching**: Commit SHAs don't change, so we can store them in DB and avoid repeated API calls
2. **Rate Limiting**: Tag resolution requires API calls - consider batching or caching
3. **Comments in YAML**: Need to handle YAML comment placement correctly
4. **Existing PRs**: Need to check for existing pinned-action PRs vs version-update PRs
