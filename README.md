# labs-tracker

Local-only pilot for tracking lab repositories and their issues with a simplified, user-controlled schema.

GitHub is the source of truth for refreshes. MongoDB stores only a small set of synced fields plus manual fields you control.

## Architecture

See [Architecture and refactoring status](docs/architecture.md) for module ownership,
dependency rules, compatibility guarantees, verification commands and remaining phases.

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
  "handlingStage": "Raised | Investigating | In progress | Waiting | Validating | Resolved",
  "waitingReason": "None | Information needed | External dependency | Review/approval | Capacity/priority | Other",
  "waitingOn": "",
  "handlingHistory": [],
  "reproductionNotes": "",
  "externalReportUrl": "",
  "externalResponse": "",
  "handlingUpdatedAt": "datetime",
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
python -m labs_tracker.cli sources-validate
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

1. **Repos**: list/create/delete repos, edit manual repo fields, sync issue data from GitHub, and run authoritative source validation with the fact-check button.
2. **Issues**: list/filter/create/delete issue records and track general resolution progress with timestamped notes, waiting reasons, investigation evidence, and optional external references.
3. **Report**: filter classification charts and resolution progress, ordered by observed unresolved hours. Compare waiting time, time by stage, delay reasons, and latest progress; open a row for its history. Use the PDF button to print the filtered report.

## Sync behavior

`sync` upserts tracked repos and issues using only GitHub-owned fields. PRs are skipped for now. For each tracked repo, sync keeps all open issues and the 10 most recently updated closed issues.

- repos: `name`, `status`, `lastUpdated`
- issues: `kind`, `title`, `state`

Manual fields are preserved across syncs via `$setOnInsert` defaults and user edits. Sync prunes repos outside `TRACKED_REPOS` and issue records outside the current window only when they have no progress history. History-bearing issues are retained for reporting, even when their repo is no longer tracked; their GitHub metadata is not refreshed outside the sync window. Explicit issue/repo deletion still removes records and their history.

Repo owners and products are selected from curated lists in the web app instead of typed as free text. Product tracking intentionally uses broad buckets such as `Foundry`, `Foundry SDK`, `Foundry Toolkit for VS Code`, `Azure Machine Learning Studio`, `Microsoft Fabric`, `Power BI`, `Azure SQL`, `GitHub Copilot`, `GitHub Actions`, `GitHub`, and `Azure DevOps`.

## Release-source validation

Repo dialogs include a source URL field for each selected product. URLs are shared across all repos using that product and saved in `productSources`; GitHub sync does not overwrite them. Edits require HTTPS on an allowlisted documentation host. After changing a URL, run the fact-check action again: validation for a different URL is not reused.

The repo table's Sources column and the repo dialog list every associated product's link and validation status. The summary counts validated sources across the entire list, not just the first product. DevOps includes Azure DevOps, GitHub, GitHub Actions, and GitHub Copilot. Source validation is not an assessment of whether a release affects lab instructions.

Foundry defaults to [Microsoft Foundry updates: July and August 2026](https://devblogs.microsoft.com/foundry/whats-new-in-microsoft-foundry-july-august-2026/). As checked on September 17, 2026, the [What's New archive](https://devblogs.microsoft.com/foundry/category/whats-new/) shows monthly roundups with occasional combined months and event editions, not a guaranteed monthly or bimonthly schedule. The July/August author note explains the combined edition as a summer-break catch-up. Slugs mix abbreviated and full month names; discover subsequent posts through the archive or [category RSS feed](https://devblogs.microsoft.com/foundry/category/whats-new/feed/) rather than constructing URLs. The app pins the selected article until it is edited; it does not automatically discover the next roundup.

Each supported product maps to an official Microsoft or GitHub release document in `release_sources.py`. The deterministic validator checks that the document is reachable, stays on an allowlisted first-party host, contains the expected product identity, and exposes recent public release evidence. It stores the final URL, check time, latest public date, HTTP status, reason, and content hash in `sourceValidations`.

Run it from the Repos page with the fact-check button or from the CLI:

```bash
python -m labs_tracker.cli sources-validate
```

A successful check proves the configured public document is recognizable and current; it does not yet determine whether a release affects a particular lab.

## Release-note agent and daily tasks

Release-impact analysis is the next phase in [docs/release-note-agent-plan.md](docs/release-note-agent-plan.md). The intended flow is:

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

### Resolution progress

The general flow is `Raised` -> `Investigating` -> `In progress` -> `Waiting` (when needed) -> `Validating` -> `Resolved`. Stages can be skipped, revisited, or reopened. `handlingStage` describes current work; `state` is GitHub-owned, `status` retains local review observations, and `resolution` describes the outcome. A GitHub closure does not silently resolve the local workflow.

Every stage or waiting-detail change requires a short progress note explaining the reason and next action. `Waiting` also requires a reason: information needed, external dependency, review/approval, capacity/priority, or other. Optionally name the person, team, or vendor. Use notes for unusual circumstances, attempted fixes, and case-specific delays instead of adding custom stages. Skillable is just one possible external dependency.

Web and CLI saves append timestamped `handlingHistory` entries with the stage, note, waiting details, and a snapshot of investigation notes and external evidence. Evidence-only edits also append an entry; unchanged saves do not. Earlier entries cannot be edited in the app. This is operational history, not a tamper-proof or actor-attributed audit log.

Timing starts at the first recorded entry, never at a guessed historical date. Reports show observed unresolved hours, waiting hours by reason/person, and elapsed time by stage. Resolved periods are excluded; reopening resumes accumulation. Notes in the same stage do not reset its age. Missing history produces blank timing, not zero. These are calendar elapsed hours, not effort, SLA compliance, or full issue age. CSV includes the history and metrics; Markdown lists the 20 longest observed records. Historical reasons and notes remain in the issue timeline even after resolution.

Legacy vendor-specific stages are mapped to general stages when displayed or normalized. Existing evidence is retained; starting history does not backdate it.

## Migrating old complex documents

If you previously synced with the old complex schema, run:

```bash
python -m labs_tracker.cli simplify --yes
```

This normalizes old data into strict `repos` and `issues` shapes, drops PR records, and removes legacy collections (`items`, `syncRuns`).
