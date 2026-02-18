<p align="center">
  <img src="./docs/logo.png" alt="ActUp logo" width="66%"/>
</p>

# ActUp

Analyse and Update (ActUp) GitHub Action versions.

[![Python 3.13](https://img.shields.io/badge/Python-3.13-blue.svg?logo=python)](https://www.python.org/downloads/release/python-3130rc1/)
[![Managed with uv](https://img.shields.io/badge/managed%20with-uv-purple.svg)](https://docs.astral.sh/uv/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Motivation

Automated workflows on GitHub often use tools like Dependabot or Renovatebot to keep their GitHub Action versions up-to-date however these are sometimes not kept up to date. **ActUp** proactively identifies these discrepancies, finds the latest stable major versions of commonly used actions, and proposes updates files across popular GitHub repositories.

## Features

*   **Action Discovery:** Identifies popular GitHub Actions.
*   **Version Tracking:** Determines the latest major version (v3, v4).
*   **Commit SHA Resolution:** Resolves version tags to exact commit SHAs for reproducible builds.
*   **Action Scanning:** Scans Action files for action usage.
*   **Auto-PR:** Forks, branches, updates, and creates Pull Requests automatically.
*   **PR Tracking:** Keeps a log of created PRs in `PR_TRACKER.md`.

## Installation

```bash
git clone https://github.com/your-org/actup.git
cd actup
uv venv
source .venv/bin/activate
make install
```

## Configuration

Set `PAT_GITHUB` environment variable.

```bash
export PAT_GITHUB="ghp_..."
```

Edit `config.yaml` as appropriate.

## Usage

Run the CLI using the `actup` command.

### Initialize
```bash
actup init-db
```

### Find Popular Actions
```bash
actup find-actions
```

### Find Popular Repositories
```bash
actup find-repos
```

### Fetch Popular Repositories
```bash
actup fetch-repos
```

### Scan Repositories
```bash
actup scan-repos
```

### Find Outdated Actions
```bash
actup find-outdated-actions
```

### Resolve Commit SHAs (optional)
```bash
actup find-action-shas
```

This resolves version tags to exact commit SHAs for more reproducible builds.

### Create Pull Requests
```bash
actup create-prs
```

To pin actions to commit SHAs instead of version tags:
```bash
actup create-prs --pin-to-sha
```

When using `--pin-to-sha`, actions are pinned to exact commits with inline comments:
```yaml
uses: actions/checkout@7a1234567890abcdef # v4.0.1
```

### Report
```bash
actup report
```

## Development

Run tests:
```bash
make test
```

Linting:
```bash
make format
```

## Terraform

ActUp can be configured to download a lot of GitHub repositories and therefore use a high network bandwidth and, when scanning, generate a high CPU workload. For these reasons it is beneficial to run ActUp on a VM with sufficient resources. In `./terraform`, run the below commands to create a VM in GCP:

```shell
terraform init
terraform plan
terraform apply
```

To run Actup:

```shell
docker run -it -e PAT_GITHUB=<TOKEN> --volume "/mnt/stateful_partition":/app/temp_scan ghcr.io/pgoslatara/actup:latest sh
```
