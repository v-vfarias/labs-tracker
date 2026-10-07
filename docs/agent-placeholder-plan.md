# Repository Agent Placeholder Plan

Status: implementation plan.

## Goal

Prove the end-to-end interaction for running one agent task against one selected
repository before adding an agent SDK, prompts, persistence, or automation.

The placeholder returns a deterministic response. It does not inspect GitHub,
call a model, modify repository data, or claim that work was performed.

## Validated Flow

1. The user opens a repository from the Repos table.
2. The repository detail dialog shows a **Run agent** action.
3. The action passes that dialog's `repo_id` to an asynchronous UI callback.
4. The callback uses `nicegui.run.io_bound` to call a normal Python service
   function without blocking the UI.
5. The placeholder service returns a structured result containing the repository,
   task name, status, and response text.
6. The UI displays the response and restores the button after success or failure.

This validates the proposed button-to-Python flow. The UI should call an imported
function rather than start a second Python process. A later CLI command can call
the same service function if script-style execution is useful for testing.

## Proposed Boundary

```text
ui/dialogs/repos.py
  Run agent button and result presentation
          |
          v
ui/actions.py
  loading state, io_bound call, error notification
          |
          v
services/repo_agent.py
  run_repo_agent(repo_id, task) -> AgentRunResult
```

The service result should be a small dataclass or typed dictionary. For the first
slice, use one fixed task such as `repository_summary` and return text similar to:

```text
Placeholder agent completed repository_summary for owner/repo.
```

## First Implementation Slice

- Add the placeholder service with no external agent dependency.
- Add one **Run agent** button to the repository detail dialog.
- Disable the button while it runs and prevent duplicate clicks.
- Display the returned repository, task, status, and response in the dialog.
- Test the service result and the UI callback's success and failure paths.
- Do not persist runs yet; the purpose is to validate control flow.

## Next Decision Gate

After the placeholder works, choose the real agent runtime and define its input,
output, authentication, timeout, cancellation, and audit requirements. Only then
replace the service implementation. The button and callback contract should stay
stable.