# Release Note Agent and Daily Task Plan

## Goal

Build a daily workflow that watches release notes for the products attached to each lab repo, flags repos that need review, and creates a small actionable task list that balances release-note reviews with issue work.

## Product Scope

Use broad product buckets so the tracker stays useful without becoming a subproduct taxonomy:

- Foundry
- Foundry SDK
- Foundry Toolkit for VS Code
- Azure Machine Learning Studio
- Microsoft Fabric
- Power BI
- Azure SQL
- GitHub Copilot
- GitHub Actions
- GitHub
- Azure DevOps

Foundry-related AI services should usually map to `Foundry` unless a lab is specifically about SDK behavior, VS Code tooling, or Machine Learning Studio.

## Data Model Additions

Add release-note review fields to `repos`:

```json
{
  "releaseReviewStatus": "Healthy | Review needed | Reviewing",
  "releaseReviewReason": "Short agent-generated explanation",
  "releaseReviewSource": "Release note title or feed/source name",
  "releaseReviewUrl": "https://...",
  "releaseReviewFlaggedAt": "datetime",
  "releaseReviewCompletedAt": "datetime"
}
```

Add a `tasks` collection:

```json
{
  "taskId": "stable string",
  "kind": "Issue fix | Release review",
  "repoId": "owner/repo",
  "issueId": "owner/repo#123 or null",
  "product": "Foundry",
  "title": "Short action text",
  "reason": "Why this task exists",
  "sourceUrl": "https://...",
  "status": "Open | Done | Skipped",
  "priority": 10,
  "createdAt": "datetime",
  "completedAt": "datetime"
}
```

## Daily Agent Pipeline

1. Load repos and their selected products.
2. Fetch release-note sources for those products.
3. Keep a cache of seen release-note item IDs or URLs so old notes do not create duplicate tasks.
4. For each new release note, ask the agent to classify possible lab impact:
   - `No likely impact`
   - `Needs human review`
   - `Likely issue`
5. For `Needs human review` or `Likely issue`, set the repo `releaseReviewStatus` to `Review needed` and store the source/reason.
6. Upsert one release-review task per repo/product/source note.
7. Generate issue-fix tasks from open issues, prioritizing unknown/unvalidated open issues.
8. Produce the daily task queue.

## Daily Task Rules

Keep the daily list small:

- Up to 5 issue-fix tasks per day.
- Up to 10 release-review tasks per day.
- Always put high-confidence release-note impacts above generic release-review tasks.
- Prefer open issues with unknown classification before closed issue cleanup.
- Do not create duplicate tasks for the same repo and release note.

## Human Review Flow

1. Open a release-review task.
2. Read the release note and inspect the affected lab repo.
3. If the lab is unaffected, mark the task `Done` and set repo `releaseReviewStatus` to `Healthy`.
4. If the lab needs a change, create or link a GitHub issue, then mark the review task `Done`.
5. If a GitHub issue was created, the normal issue task workflow handles the fix.

## Manual Run First, Daily Later

Start with a manual CLI command:

```bash
python -m labs_tracker.cli release-scan
python -m labs_tracker.cli tasks --daily
```

After the workflow is stable, run it daily with Windows Task Scheduler:

```powershell
$Action = New-ScheduledTaskAction -Execute "C:\Users\Public\Documents\labs-tracker\.venv\Scripts\python.exe" -Argument "-m labs_tracker.cli release-scan" -WorkingDirectory "C:\Users\Public\Documents\labs-tracker"
$Trigger = New-ScheduledTaskTrigger -Daily -At 8:00AM
Register-ScheduledTask -TaskName "LabsTrackerReleaseScan" -Action $Action -Trigger $Trigger -Description "Scan product release notes for lab impact"
```

## Implementation Phases

1. Add repo release-review fields and a `tasks` collection with indexes.
2. Replace mocked release signals with product source configuration.
3. Add release-note fetchers using RSS or public docs pages where available.
4. Add deduplication for seen release notes.
5. Add a local agent/evaluator step that scores release-note relevance against repo metadata.
6. Add `release-scan` and `tasks --daily` CLI commands.
7. Add web UI for release-review tasks and completion.
8. Add Windows Task Scheduler setup docs after manual scans are reliable.
