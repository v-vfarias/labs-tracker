# Suggested Daily Tasks and Weekly Work Log

Status: minimal manual prototype implemented, updated 2026-10-02.
This extends the existing release-note agent plan. The implemented slice below
is distinct from the broader target design and future automation.

## Implemented Prototype

- One Tasks view in the existing NiceGUI page/server, reached from Repos; no new port.
- Manual task creation, persistent backlog, uncapped Today selection, and carry-over.
- On-demand suggestions only for locally unresolved issues/PRs pending
  classification, in review, or waiting for information. No tasks from missing
  test dates or repo changes alone; no GitHub/release fetching or automatic selection.
  Issue validation is also available as a manual task type.
- Open, In progress, Deferred, Done, and Won't do; progress notes, reason validation,
  reopening, event snapshots, idempotent retries, and version-checked saves.
- Weekly preview and Markdown/CSV downloads using Monday-start weeks in the
  machine's local timezone. Distinct-task totals, decision/activity events, and
  outstanding state at cutoff are separate.
- History retained independently of repo/issue deletion. No task-deletion UI.

Use **New task** or **Suggest from stored data**, open a row in Backlog, then
**Select for today**. Tasks not selected remain in Backlog. Deferred work becomes
available on its revisit date but is not automatically selected.

Prototype boundaries: evidence and follow-up references are free-text notes plus
an optional source URL, not structured PR verdict/revision or release-coverage
forms. Issue classification is saved separately in Issues. No automatic recurrence,
PR ingestion, release discovery, freshness tracking, source-unavailability checks,
or impact inference is included. Source snapshots are retained, but source fetching
and review checkpoints await later phases.

Suggestion deduplication uses the current rule reason and repo/item identifier.
Task refresh and suggestion generation retire ineligible generated work as
Won't do / Superseded / obsolete with an automatic history note, never as Done.
Generation may reopen automatically retired work if the source qualifies again,
but preserves human completion/rejection decisions. Manual tasks are not retired.
Substantive source revisions are not detected; manually reopen an assessment or
create a new task when needed. Existing report APIs remain, using the narrowed rules.

Eligibility: `Resolved` handling stage or `Resolved locally`, `Closed`, or
`Not applicable` local status overrides missing classification. For unresolved
items, `Waiting` / `Information needed` takes precedence, followed by `In review`,
`Waiting owner review`, or `Validating`, then unknown/missing/invalid type or
resolution. Only one next action is suggested per source. GitHub state is unchanged.

Repository/issue saves now offer **Tested now**, default No (keep the previous
timestamp). Yes stamps the current save time; the date is read-only, not an input.
The same rule applies to CLI classification and does not execute tests.

A one-time, explicitly confirmed local baseline can mark current issues
`Resolved locally` / `Resolved` and stamp repo/issue test dates. It appends a
user-asserted baseline note and preserves GitHub state, classifications, and prior
evidence/history. Back up the collections before applying it; it is not a sync rule
and must not automatically resolve newly imported issues.

## Goal

Help a lab maintainer inspect repository health and anticipate product changes
without facing an overwhelming automated work queue. Turn suggestions into
deliberate daily choices and retain an evidence-bearing record for weekly reports.

Repository health here means reviewing issues, classifying them in the tracker,
assessing PR suggestions, and checking product changes against tracked labs. It
does not mean that a reachable source, a completed checklist, or an empty queue
proves that a lab works.

## Confirmed Decisions

- Maintain one persistent backlog. Unfinished tasks carry forward without being
  duplicated each day or discarded at the end of a week.
- Let the user choose today's tasks manually, with no automatic daily limit.
  Suggestions may be ranked, but the system does not assign work to Today.
- Support marking work done and retaining it for a later weekly work report.
- Support `Won't do` only with a selected reason or a supplied description.
- Cover repository inspection, issue classification, PR validation, and release
  reading/cross-checking for possible upcoming lab problems.
- The minimal manual slice and suggestions from already-stored records are approved.
- Use Monday-start weeks and the machine's local timezone for daily/weekly dates.

The remaining detailed design below is the target, not a promise that every
surface is included in the minimal prototype.
This replaces the earlier proposal for daily quotas of 5 issue fixes and 10
release reviews, and replaces the ambiguous `Skipped` state.

## Existing Foundation and Gaps

| Area | Implemented today | Required addition |
| --- | --- | --- |
| Suggestions | [Task service](../src/labs_tracker/services/tasks.py) selects unresolved classification/review/details work; [work log service](../src/labs_tracker/services/worklog.py) persists and reconciles generated tasks | Meaningful source-revision detection |
| Issues | Manual classification, evidence, and timestamped handling history | Link task outcomes to the existing workflow without conflating their states |
| PRs | Task/report logic recognizes stored PR records, but normal sync skips PRs | Read-only PR ingestion and review evidence; recognition alone is not working PR coverage |
| Product sources | Configured first-party sources and deterministic validation | Discover individual updates, retain review checkpoints, and assess lab impact |
| Reporting | [Report service](../src/labs_tracker/services/reports.py) preserves issue exports and adds event-based weekly task exports | Structured coverage/evidence reporting |
| Interface | Repos, Issues, Report, and Tasks with Today/Backlog/History and weekly controls | Type-specific evidence forms |

Source validation runs from the Repos fact-check action or
`python -m labs_tracker.cli sources-validate`. `sourceValidations` stores provenance,
freshness, URL, HTTP status, content hash, and check time; it is not impact analysis.

Issue handling remains `Raised`, `Investigating`, `In progress`, `Waiting`,
`Validating`, and `Resolved`, with notes and waiting reasons. Its elapsed-time
metrics are not effort. Task status must remain separate from issue handling,
local classification, and GitHub open/closed state.

Use the existing broad product catalog and shared source overrides: Foundry,
Foundry SDK, Foundry Toolkit for VS Code, Azure Machine Learning Studio, Microsoft
Fabric, Power BI, Azure SQL, GitHub Copilot, GitHub Actions, GitHub, and Azure DevOps.
Do not introduce a parallel product taxonomy.

## Task Types and Completion Evidence

| Type | Suggested work unit | What counts as done |
| --- | --- | --- |
| Repository health review | Inspect a repo's open issues, PR coverage, and outstanding signals | Checklist and summary of what was checked; link follow-up tasks for unresolved findings |
| Issue triage | Inspect one issue and classify it in the platform | Saved classification plus a short assessment or linked issue-history entry |
| PR validation | Assess one PR's relevance, proposed change, and supporting evidence | Verdict and rationale; record tests performed or explicitly state what was not tested |
| Product update review | Read new release notes for a product since the last completed review | Record sources and review coverage; identify potentially affected repos or explain no likely impact |
| Lab impact check | Cross-check a specific product change against a specific lab | Record affected instructions/dependencies and an impact verdict, with follow-up when needed |

Proposed PR verdicts: `Valid suggestion`, `Needs changes`, `Not applicable`,
and `Unable to verify`. Completing an assessment is not an approval, merge, or
claim of successful execution. If verification is still required, leave the task
open/deferred or complete the assessment with an explicit linked follow-up.

Proposed impact verdicts: `No impact found`, `Potential impact`, and
`Confirmed impact`. Include the affected product/version, relevant lab step or
file, source link, and effective/deprecation date when known. Product-level reading
can cover multiple repos; create repo-specific checks only where warranted.

Issue fixes and retests can be added as manual follow-up tasks. Do not require
fixing an issue to finish triage or validating every lab to finish reading a release.

## Daily and Weekly Workflow

1. Refresh available source data on demand. Show last successful refresh and any
   source/repo failures; a failed check is not "nothing new."
2. Browse ranked suggestions in Backlog, filtered by repo, product, and task type.
   Explain why each suggestion exists and show source freshness.
3. Select any number of tasks for Today, or add a manual task with a relevant link.
4. Inspect the evidence and record progress. Choose Done, Defer, or Won't do.
5. Show unfinished previously selected tasks as carry-over on later days. Allow
   returning a task to Backlog without treating it as completed or rejected.
6. At weekly review, summarize completed work, decisions not to proceed, and
   remaining work separately. Keep unresolved tasks in the same backlog.

Today is a view/selection, not a task status. Reading source data daily must not
create a daily copy of every unresolved task. Scheduled refresh is optional later;
the prototype must work without a background scheduler or AI service.

### Suggested Prioritization

Rank known breaking changes/deprecation deadlines and active lab failures first,
then unclassified issues, PR assessments, product updates, and routine reviews.
Surface aging tasks so lower-ranked work does not disappear indefinitely.
Show the reason for ranking; confidence is distinct from urgency. Manual choice
always wins, with no hidden quota or automatic selection.

## Task Lifecycle and Decisions

Proposed states: `Open`, `In progress`, `Deferred`, `Done`, and `Won't do`.

- Done requires an outcome summary and completion timestamp. Evidence links are
  optional unless the task-specific outcome requires one.
- Defer requires a revisit date and may include a note. It stays in Backlog,
  stays out of Today until due, and becomes available again when due without
  being automatically selected. Lack of time is deferral, not rejection.
- Won't do requires a reason code or nonblank custom description. Selecting a
  standard reason is sufficient except where supporting detail is required below.
- Reopening Done or Won't do requires a note and retains the previous decision.
  Correcting outcomes must append history rather than rewrite earlier evidence.
- Generation/refresh must not reset user state, notes, deferral, or selection.
  Source closure/deletion alone must not silently mark local work Done.
- A reviewed change that does not affect the lab is Done with `No impact found`,
  not Won't do: the investigation was useful work.

### Proposed Won't Do Reasons

| Reason | Supporting detail |
| --- | --- |
| Out of scope | Optional description of the boundary |
| Duplicate | Required link/reference to the original task or tracked work |
| Superseded / obsolete | Optional replacement or changed circumstance |
| Already handled elsewhere | Required link or description of where it was handled |
| Not relevant to tracked labs | Optional explanation; use Done if an impact review was performed |
| Accepted risk / low value | Required rationale describing the trade-off |
| Other | Required nonblank description |

Whitespace-only input is invalid. Show validation errors without closing the
dialog or changing the task. Won't do applies to this task/signal only; it must
not suppress all future updates for the repository or product.

## Prototype Screens

**Tasks / Today**

- Selected work and an explicit carry-over section; counts by state/type.
- Rows show type, repo/product, title, suggestion reason, age, and source freshness.
- Actions: Start, Done, Defer, Won't do, Return to backlog, and View history.
- Empty state directs the user to select from Backlog, not an automatic task fill.

**Tasks / Backlog**

- Filters for type, repo, product, status, and revisit date; ranked suggestions.
- Select for Today and manual task creation. No automatic daily limit.
- Separate completed/declined history from actionable work; allow reopening.

**Task detail**

- Source links, associated issues/PRs, review scope, and evidence.
- Outcome form appropriate to task type; Won't do reason selector and note field.
- Append-only timeline of state changes, outcomes, and follow-up references.

**Report / Weekly work**

- Week/date-range selection, totals by type/repo/product, and Markdown/CSV export.
- Completed work with outcomes and links; Won't do decisions with reasons.
- Deferred/open carry-over and known coverage gaps in separate sections.
- Preserve existing issue-progress reporting and existing exports.

## Proposed Persistence and Deduplication

Use a new `tasks` collection, not extra statuses on `issues`. A task should retain:

| Fields | Purpose |
| --- | --- |
| `taskId`, `dedupeKey`, `kind` | Stable identity and unique work-unit key |
| `repoIds`, `product`, `issueId`, `prUrl` | Optional scope; product reading may span repos |
| `title`, `reason`, `sourceRefs`, `sourceRevision` | Explain the suggestion and preserve its source |
| `status`, `selectedForDate`, `deferredUntil` | State, local-date selection, and revisit date |
| `createdAt`, `updatedAt`, `completedAt` | UTC timestamps; completion projection is not the history |
| `outcome`, `wontDoReason`, `decisionNote`, `followUpRefs` | Current human decision and evidence |
| `history` | Timestamped events with previous/new state and outcome/source/scope snapshots |

For a small single-user prototype, embedded history allows one atomic task update.
Use unique `taskId`/`dedupeKey` indexes, event IDs to make retried actions idempotent,
and an update-version guard so two UI sessions cannot silently overwrite decisions.
Keep domain validation in domain code and database writes in services.

Deduplication keys describe the work, not the scan date:

- Issue triage: repo + issue identifier + action + relevant source revision (future;
  the prototype uses the current eligibility reason rather than a source revision).
- PR validation: repo + PR identifier + reviewed head revision.
- Product reading: product + stable release item ID/revision.
- Lab impact check: repo + product + release item ID/revision.
- Routine repo review: repo + explicit review period, when recurrence is enabled;
  repository-only automatic suggestions are currently disabled.

Do not treat unrelated metadata or page-layout changes as new substantive work.
Repeated scans reuse the same task, including Done/Won't do decisions. A meaningful
new source revision may create a linked follow-up rather than silently reopening a
completed task. Track the reviewed revision so a changed PR is not reported as
validated against its new head.

Store source refresh/checkpoints separately from task completion: fetched/seen is
not read/reviewed. Advance review coverage only for the items actually reviewed.
Preserve task snapshots if source records are pruned or a repo stops being tracked;
mark unavailable sources visibly. Explicit task-history deletion policy needs
approval before implementation and must not piggyback on current repo deletion.

## Weekly Work Report Semantics

Confirmed prototype default: Monday through Sunday in the server machine's local
timezone. Store event instants in UTC; resolve each local midnight separately to
form the half-open UTC interval `[start, next week start)`, including DST changes.
Changing the machine timezone changes subsequent report/date interpretations;
per-user timezone preferences are not part of this slice.

- Include work by the date of the recorded completion/decision, not creation date
  or current GitHub state. A task created last week and completed this week belongs
  in this week's completed work.
- Read durable task history, never infer completed work from today's suggestions.
- Count distinct tasks with completion events; show repeat completions/reopenings
  in the timeline rather than inflating the completed-task total.
- A later reopening does not erase earlier work. Identify reopened tasks and
  corrections explicitly; use event snapshots for historical titles and outcomes.
- Keep Won't do counts and reasons separate from completed-work totals.
- Show carry-over as of the period end, reconstructed from state/selection events.
  For an ongoing week, label it as of the report generation time.
- Include report range, timezone, generation time, source coverage gaps, evidence,
  and follow-ups. No invented effort estimates or productivity score.
- Exported reports are saved snapshots; a later export may include later-recorded
  corrections. Do not promise immutable or tamper-proof audit reporting.

Example: an issue classified Monday and a release found harmless Tuesday are two
completed tasks. A duplicate PR-review task declined Wednesday is one Won't do
decision. A lab impact check deferred to next week remains outstanding work.

## Release Monitoring and Health Signals

1. Reuse configured authoritative product sources and their validation.
2. Discover stable release items and retain title, publication/effective dates,
   URL, revision, and fetch status. Avoid constructing guessed monthly URLs.
3. Present updates for human reading first, with related repos/products.
4. Cross-check likely changes against lab instructions, dependencies, and versions.
5. Record an impact verdict and link follow-up work. Creating a GitHub issue is a
   separate explicit user action, not an automatic result of analysis.

Later AI assistance may propose `No likely impact`, `Needs human review`, or
`Likely issue`, but must include source citations, affected lab evidence, and
uncertainty. Product membership alone is insufficient evidence of a defect.

Prefer release-review coverage labels such as `Review needed`, `Reviewed through
<date/revision>`, and `Unknown / source unavailable` over a blanket `Healthy`.
Completing one task must not clear other outstanding repo impacts. An accepted
risk or Won't do decision is not proof of health.

## Delivery Sequence

1. **Confirm prototype decisions:** minimal scope and local Monday-start weeks
   approved; remaining automation decisions are listed below.
2. **Manual vertical slice:** persistent task CRUD, manual Today selection,
   carry-over, decision validation, history, and weekly export. Support all task
   types with manual evidence/links, including PRs and release notes. **Implemented.**
3. **Existing-data suggestions:** adapt current task-generation rules into
   idempotent persisted suggestions without breaking existing report behavior.
   **Implemented**, with revision limits documented above.
4. **Read-only PR coverage:** add ingestion, freshness, head-revision tracking,
   and assessment UI. Revisit legacy normalization that removes PR records.
5. **Release discovery:** authoritative item fetchers, checkpoints, deduplication,
   product reading and per-lab follow-ups, with explicit partial-failure handling.
6. **Optional assistance/automation:** scheduled daily refresh and evidence-backed
   impact suggestions only after manual operation is reliable.

Potential future CLI names are `release-scan` and `tasks --daily`; these are not
implemented commands or setup instructions. Schedule only after retry/failure
behavior is tested. No automatic merges, issue closures, GitHub comments, or fixes.

## Acceptance Scenarios for Implementation

1. Refreshing unchanged inputs twice creates one task per work unit and preserves
   any completion, Won't do, notes, deferral, and Today selection.
2. Selecting zero, one, or more than fifteen tasks works without an automatic cap;
   refreshing does not select additional tasks.
3. An unfinished Monday selection is visible as carry-over Tuesday and survives
   the week boundary; no duplicate daily instance is created.
4. Done persists its outcome, timestamp, and evidence across app restarts and
   appears in the week of completion, even if created earlier.
5. Won't do rejects an empty reason/description and whitespace-only custom text;
   standard reasons, custom descriptions, and required supporting details follow
   the rules above. Rejected saves leave state unchanged.
6. Deferral hides work from Today until its revisit date; due work is available
   without automatic selection and is not counted as Done or Won't do.
7. Reviewing a release with no lab impact records completed work. A possible
   impact includes a rationale and linked follow-up; other impacts remain visible.
8. PR assessments preserve the reviewed head and test limitations. A later head
   revision is not silently covered by the earlier verdict.
9. A failed source fetch produces a visible coverage gap, preserves older work,
   and does not mark the repo healthy or advance the reviewed checkpoint.
10. Weekly exports separate completed work, declined decisions, and carry-over;
    test timezone/week boundaries, reopening, repeat completion, and later edits.
11. Source pruning or repo untracking does not remove historical work evidence;
    repeated saves do not append duplicate events and concurrent edits conflict
    explicitly rather than losing data.
12. Existing issue classification, sync ownership, source validation, and report
    outputs retain their behavior until explicitly integrated and tested.

## Open Decisions Before Further Implementation

- Routine health-review cadence: daily per repo, weekly per repo, or manually
  requested? Daily refresh availability does not imply daily checklist creation.
- Refine structured task-specific outcome requirements after using the note-based
  prototype; the proposed states and Won't do reason catalog are implemented.
- Define when a source change is meaningful enough for a new suggestion, including
  the first-run release lookback so old history does not flood the backlog.
- Confirm any future explicit deletion/retention behavior for task history. The
  prototype retains history and offers no delete action.

## Potential Improvements After the Prototype

- Batch product reading shared by many repos, while retaining per-lab impact work.
- Show a coverage matrix of repos/products last reviewed, separate from task counts.
- Highlight approaching deprecations and review age without forcing daily quotas.
- Add estimated effort or a voluntary time budget only if useful; never infer
  actual effort from elapsed task age.
- Learn from Won't do reasons to propose better filters, with user approval before
  suppressing future suggestions.
- Provide evidence-backed AI summaries as drafts, with human-controlled decisions.
