# labs-tracker

Local-only pilot for tracking lab repository issues, pull requests, validation, and resolution evidence.

The first pilot repository is [`MicrosoftLearning/mslearn-ai-language`](https://github.com/MicrosoftLearning/mslearn-ai-language). GitHub remains the source of truth for repository, issue, and pull request metadata. MongoDB stores the synced GitHub data plus manually maintained validation/classification fields that help explain how the lab is doing.

This is intentionally a personal/local pilot, not a hosted application.

## What “tested” means

In this pilot, **tested** means you checked a GitHub issue or pull request and verified the behavior:

- for an issue, whether the reported problem reproduces;
- for a pull request, whether the proposed fix validates for maintainers.

## Data model

MongoDB uses three collections:

- `repos` — one document per tracked GitHub repository/lab.
- `items` — one document per GitHub issue or pull request.
- `syncRuns` — one document per sync attempt.

Daily refreshes overwrite GitHub-owned fields such as titles, labels, assignees, issue state, PR branch, draft state, timestamps, and repository metadata. Manual fields are only created for new items and are preserved on later syncs:

- `typeOfIssue`
- `resolution`
- `status`
- `testResult`
- `lastTested`
- `notes`

## Setup

### 1. Create your environment file

```bash
cp .env.example .env
```

Edit `.env` and add a GitHub token:

```env
MONGO_URI=mongodb://localhost:27017
MONGO_DB=labs_tracker
GITHUB_TOKEN=<your-github-token>
TRACKED_REPOS=MicrosoftLearning/mslearn-ai-language
```

### 2. Start MongoDB

```bash
docker compose up -d
```

MongoDB runs locally on `localhost:27017` and persists data in a named Docker volume.

### 3. Install Python dependencies

Using a virtual environment is recommended:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

### 4. Run the initial GitHub sync

```bash
python -m labs_tracker.cli sync
```

The first sync creates or updates the repo document and issue/PR item documents for the tracked repository. Running sync again updates GitHub metadata while preserving manual validation fields.

### 5. View generated tasks

```bash
python -m labs_tracker.cli tasks
```

Tasks are generated dynamically from MongoDB state. Examples include unclassified issues/PRs, open issues needing reproduction checks, open non-draft PRs needing validation, repos changed after last testing, closed items without validation, and aging untested PRs.

### 6. Classify and validate items

```bash
python -m labs_tracker.cli classify
```

The command lists unclassified or untested items, then prompts for:

- issue type
- resolution
- manual status
- test result
- last tested date
- notes

### 7. Open the Streamlit dashboard

```bash
streamlit run app.py
```

Dashboard views include:

- Repo health overview
- Issue breakdown
- PR validation queue
- Tasks of the day
- Recently closed/resolved items

Filters are available by repo, kind, status, type, and test result where practical.

### 8. Export reports

```bash
python -m labs_tracker.cli export
```

This writes the following files to `reports/`:

- `report.md`
- `repos.csv`
- `items.csv`
- `tasks.csv`

`reports/` is ignored by Git because reports are local generated output.

## CLI commands

```bash
python -m labs_tracker.cli sync
python -m labs_tracker.cli tasks
python -m labs_tracker.cli classify
python -m labs_tracker.cli export
```

If installed with `pip install -e .`, you can also run:

```bash
labs-tracker sync
labs-tracker tasks
labs-tracker classify
labs-tracker export
```
