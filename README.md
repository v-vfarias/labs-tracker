# labs-tracker

Local-only pilot for tracking lab repositories and their issues/PRs with a simplified, user-controlled schema.

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
  "kind": "Issue | PR",
  "title": "String",
  "state": "Open | Closed",
  "typeOfIssue": "UI drift | Outdated version | Nice to have | Skillable capacity | Product consistency | Unknown",
  "resolution": "Updated UI or code or versions | Commented or added the requested content | Report to Skillable | Added note or warning | Not applicable | Unknown",
  "status": "Closed | In review | Not applicable | Open",
  "lastTested": null
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
TRACKED_REPOS=MicrosoftLearning/mslearn-ai-language
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
python -m labs_tracker.cli tasks
python -m labs_tracker.cli classify
python -m labs_tracker.cli export
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

1. **Repos**: list/create/delete repos and edit manual repo fields (`involvedDevs`, `products`, `lastTested`).
2. **Issues/PRs**: list/filter/create/delete issue/PR records and edit manual fields (`typeOfIssue`, `resolution`, `status`, `lastTested`).
3. **Tasks**: generated task queue from the simplified model.
4. **Reports/Export**: sync, simplify existing data, and export reports.

## Sync behavior

`sync` upserts tracked repos and open issues/PRs (plus recently closed records) using only GitHub-owned fields:

- repos: `name`, `status`, `lastUpdated`
- issues: `kind`, `title`, `state`

Manual fields are preserved across syncs via `$setOnInsert` defaults and user edits.

## Migrating old complex documents

If you previously synced with the old complex schema, run:

```bash
python -m labs_tracker.cli simplify --yes
```

This normalizes old data into strict `repos` and `issues` shapes and removes legacy collections (`items`, `syncRuns`).

## Exports

`export` writes local files under `reports/`:

- `report.md`
- `repos.csv`
- `issues.csv`
- `tasks.csv`
