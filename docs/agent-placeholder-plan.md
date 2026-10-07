# Foundry Release-Check Pilot

## Milestone 1

Implemented for MicrosoftLearning/mslearn-ai-agents with a mock analyzer:

- Repo dialog and headless CLI share a native async Python service.
- Official RSS/archive discovery and article extraction are real and bounded.
- Canonical URLs identify articles; normalized content hashes detect edits.
  Unreconciled redirected identities fail coverage checks, not pass as unchanged.
- First check establishes the baseline and invokes the mock. Reuse requires
  matching source scope, selected-file hashes, backend and analyzer version.
- GitHub evidence is pinned to a commit, with paths, blob hashes, line counts and
  source links. Default scope is Exercises plus numbered Python lab files.
- Mock output states impact is not assessed. No real summary or risk verdict is
  claimed, and no revision findings are fabricated.
- Existing findings survive later checks. Review requires a note and a matching
  state version. Repo lifecycle status remains Live/Archived.

## Persistence

`releaseSnapshots` holds immutable normalized articles and raw/semantic hashes.
`releaseCheckRuns` holds attempt/review evidence. `repoReleaseChecks` is the
authoritative publication point: only its referenced successful run and review
represent accepted state. Unreferenced history documents can exist after a lost
compare-and-set or crash; never infer current state from the newest history row.
Failures remain separate from the last successful comparison/assessment baseline.

A ten-minute Mongo lease and five-minute run deadline bound execution. Publication
checks token, expiry, version and current source configuration. Superseded workers
cannot publish or unlock a newer worker. No replica-set transaction is required.
Source changes reset comparison scope but retain findings. Global validation is
updated only for the exact saved URL fetched; it is never an impact verdict.

Review notes have timestamps but no authenticated actor identity. This is not a
multi-user audit trail. History has no automatic retention policy yet.

## Milestone 2: GitHub Copilot SDK

After accepting the first flow, implement the local Python Copilot SDK analyzer,
not GitHub Actions or an Azure-hosted agent. Preserve the UI/service boundary.
Lazy-load the SDK behind an optional dependency and explicit live setting; keep
base Python 3.10 support while requiring a supported newer interpreter for live use.

Validate structured summaries/findings with article and lab citations, severity
and confidence. Treat fetched material as untrusted evidence, not instructions.
Use deny-by-default permissions/tools, no shell/file/GitHub writes, bounded inputs
and outputs, explicit cancellation and session/client cleanup. Require live
provenance before publishing real revision findings. Harmless later checks must
not clear previous findings. Test authentication, permissions, model errors,
malformed output and cancellation before enabling live use.
`RELEASE_CHECK_BACKEND=copilot` currently fails explicitly, without mock fallback.

## Verification

Run `python -m unittest discover -s tests -v`. Set
`LABS_TRACKER_RUN_MONGO_TESTS=1` for isolated local MongoDB tests. These create and
drop uniquely named test databases, never the working database. Live smoke checks
also use isolated databases; publisher markup and GitHub file selection can change
independently of deterministic fixtures.