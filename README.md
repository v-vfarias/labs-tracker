# labs-tracker

Local-only pilot for tracking lab repositories and their issues with a simplified, user-controlled schema.

GitHub is the source of truth for refreshes. MongoDB stores only a small set of synced fields plus manual fields you control.

## Simplified data model

Two primary collections are used:

- `repos`
- `issues`

### `repos`

```json
{
  "id": "owner/repo",
  "name": "repo",
  "involvedDevs": [],
  "products": ["Azure AI Language"],
  "status": "Archived | Live",
  "lastUpdated": "datetime",
  "lastTested": null
}
```

### `issues`

```json
{
  "issueId": "owner/repo#123",
  "repoId": "owner/repo",
  "kind": "Issue",
  "title": "String",
  "state": "Open | Closed",
  "typeOfIssue": "UI drift | Skillable | SDK/code issues | Outdated versions | User intent/setup mismatch | Lab content clarity | Product/service behavior | Enhancement request | Unknown",
  "resolution": "Fixed in lab | Linked PR | Replied/no lab change | Reported externally | Duplicate | Cannot reproduce | Not applicable | Unknown",
  "status": "Closed | In review | Resolved locally | Waiting owner review | Temporary/out of scope | Not applicable | Open",
  "lastTested": null,
  "closingPrUrl": ""
}
```

## Setup

### 1) Configure `.env`

```bash
cp .env.example .env
```

Set values:

```env
MONGO_URI=mongodb://localhost:27017
MONGO_DB=labs_tracker
GITHUB_TOKEN=<your-github-token>
TRACKED_REPOS=MicrosoftLearning/mslearn-ai-agents,MicrosoftLearning/mslearn-ai-fundamentals,MicrosoftLearning/mslearn-ai-language,MicrosoftLearning/mslearn-ai-studio,MicrosoftLearning/mslearn-ai-vision,MicrosoftLearning/mslearn-devops,MicrosoftLearning/mslearn-genaiops,MicrosoftLearning/mslearn-mlops,MicrosoftLearning/mslearn-azure-ai,MicrosoftLearning/mslearn-ai-information-extraction,MicrosoftLearning/dp-300-database-administrator,MicrosoftLearning/PL-300-Microsoft-Power-BI-Data-Analyst,MicrosoftLearning/mslearn-sql-developer
```

### 2) Start local MongoDB

```bash
docker compose up -d
```

### 3) Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

## Main commands

```bash
python -m labs_tracker.cli sync
python -m labs_tracker.cli simplify --yes
python -m labs_tracker.cli classify
python -m labs_tracker.cli web
```

If installed with `pip install -e .`, you can use `labs-tracker <command>`.

## Local CRUD web app (NiceGUI)

Run:

```bash
python -m labs_tracker.web
```

or:

```bash
python -m labs_tracker.cli web
```

Default URL: `http://127.0.0.1:8080`

Pages:

1. **Repos**: list/create/delete repos, edit manual repo fields, and sync issue data from GitHub.
2. **Issues**: list/filter/create/delete issue records and edit manual fields (`typeOfIssue`, `resolution`, `status`, `lastTested`, `closingPrUrl`). Clicking an issue opens a dialog with its GitHub link and manual classification controls.

## Sync behavior

`sync` upserts tracked repos and issues using only GitHub-owned fields. PRs are skipped for now. For each tracked repo, sync keeps all open issues and the 10 most recently updated closed issues.

- repos: `name`, `status`, `lastUpdated`
- issues: `kind`, `title`, `state`

Manual fields are preserved across syncs via `$setOnInsert` defaults and user edits. Sync also prunes repos outside `TRACKED_REPOS`, PR records, and stale issue records outside the current open/latest-closed window.

Repo owners and products are selected from curated lists in the web app instead of typed as free text. Product tracking intentionally uses broad buckets such as `Foundry`, `Foundry SDK`, `Foundry Toolkit for VS Code`, `Azure Machine Learning Studio`, `Microsoft Fabric`, `Power BI`, `Azure SQL`, `GitHub Copilot`, `GitHub Actions`, `GitHub`, and `Azure DevOps`.

## Release-note agent and daily tasks

The next feature phase is planned in [docs/release-note-agent-plan.md](docs/release-note-agent-plan.md). The intended flow is:

- fetch release notes for each repo's selected products
- flag repos as needing review when a product change may affect labs
- create release-review tasks and issue-fix tasks
- keep daily issue work capped around 5 fixes, with faster release reviews batched separately
- mark review tasks done to return repos to a healthy state, or create/link issues when lab changes are needed

## Classification guidance

Use `typeOfIssue` for the root problem category:

- `UI drift`: screenshots, portal flows, buttons, menus, labels, or UX changed.
- `Skillable`: hosted lab environment, capacity, VM, credentials, or lab platform issue.
- `SDK/code issues`: sample code, SDK API, imports, generated code pattern, or runtime error needs updating.
- `Outdated versions`: package, SDK, API, CLI, model, runtime, or dependency version drift.
- `User intent/setup mismatch`: user used the lab with the wrong intent, skipped expected setup, missed prerequisites, or reported a setup problem that is not a lab defect.
- `Lab content clarity`: instructions, wording, order, warning notes, or expected outcomes are unclear.
- `Product/service behavior`: non-UI product behavior, service limitation, region/quota/RBAC behavior, or naming consistency changed.
- `Enhancement request`: nice-to-have, modular suggestion, or lab-specific suggestion rather than a defect.

Use `status` for your working state, which may differ from GitHub's open/closed state:

- `Resolved locally`: you consider the issue resolved even if GitHub is still open.
- `Waiting owner review`: your fix or response is ready, but the owner has not reviewed or merged it yet.
- `Temporary/out of scope`: the issue is currently beyond lab scope, transient, or owned by another system.
- `In review`: actively being assessed or validated.
- `Not applicable`: no action needed for this lab.

Use `resolution` for the outcome, not the root cause. It is intentionally compact so reports group cleanly:

- `Fixed in lab` when instructions, code, warnings, or versions changed in the lab repo.
- `Linked PR` when the issue is addressed by a PR tracked in `closingPrUrl`.
- `Replied/no lab change` when the response resolves the issue without changing the lab.
- `Reported externally` when the fix belongs to Skillable, product/service engineering, or another owner.
- `Duplicate`, `Cannot reproduce`, or `Not applicable` when no repo change is needed.

Use `closingPrUrl` when an issue was closed or addressed through a PR. The Issues table shows a small `PR` button when this field is set.

## Migrating old complex documents

If you previously synced with the old complex schema, run:

```bash
python -m labs_tracker.cli simplify --yes
```

This normalizes old data into strict `repos` and `issues` shapes, drops PR records, and removes legacy collections (`items`, `syncRuns`).
