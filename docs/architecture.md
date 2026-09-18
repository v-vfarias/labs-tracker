# Architecture and Refactoring Status

The tracker remains a local Python application using Typer, NiceGUI and MongoDB.
This refactor changes code ownership, not features, database schemas or appearance.

## Implemented Structure

```text
src/labs_tracker/
  cli.py                     Terminal entry point and prompting
  web.py                     Existing NiceGUI page composition and callbacks
  config.py                  Settings and environment loading
  db.py                      MongoDB connections and indexes
  domain/
    models.py                Classification values, aliases and defaults
    workflow.py              Progress history rules and elapsed-time metrics
    products.py              Product display defaults and normalization
  services/
    tracking.py              Tracking input parsing and classification queries
    sync.py                  Upserts, sync window and history retention
    maintenance.py           Explicitly confirmed legacy normalization
    tasks.py                 Task generation from database records
    reports.py               Report queries, metrics, Markdown and CSV export
  integrations/
    github.py                GitHub client creation, fetching and mapping
    release_sources.py       Source catalog, validation and result persistence
  ui/
    formatting.py            Date, label, link and table-event formatting
    theme.py                 Package-resource stylesheet loader
    assets/tracker.css       Screen, responsive and print styling
```

Each package has a minimal `__init__.py`; importing one does not start the app.
The old root modules for models, workflow, tasks, report, sync and release sources
remain explicit compatibility re-exports. New code imports the owning package.
Do not create a `web/` package alongside the existing web entry-point module.

## Dependency Rules

- Domain code uses only the standard library and other domain modules. Existing
  MongoDB-shaped progress-update dictionaries remain part of its contract, but
  it never executes database operations.
- Services own application operations and may use domain rules, integrations,
  configuration and database helpers. Pass database/client collaborators at
  testable boundaries; no dependency-injection framework is needed.
- Integrations never import services or presentation. Release-source validation
  retains its existing injected database, HTTP opener and clock parameters.
- UI code owns widgets, notifications and client-local state. Once the next phase
  is complete, database reads/writes will reside in services, not UI callbacks.
- CLI imports do not load NiceGUI. The web command imports the web entry point
  lazily. No import should create connections, perform network I/O or start a server.
- Split by responsibility, not a strict line-count limit. Avoid generic utility
  buckets, an event bus, an ORM or a new frontend framework for this refactor.

These rules are checked in `tests/test_architecture.py` where implemented.

## Preserved Contracts

- `labs-tracker`, `python -m labs_tracker.cli`, and `python -m labs_tracker.web`
  retain their existing commands, options and default host/port.
- Public functions/constants defined by the compatibility modules retain their
  identities and signatures. Private helpers and accidentally imported dependency
  names are not public compatibility APIs.
- Patch dependencies where the implementation looks them up. For example, sync
  tests now patch `labs_tracker.services.sync.get_database` and `get_github`;
  maintenance tests patch `labs_tracker.services.maintenance.get_database`.
- Sync still skips PRs, preserves manual fields, and retains history-bearing issues
  outside the sync window. Destructive normalization still requires confirmation.
- Stored product defaults and display fallbacks intentionally remain distinct.
- Web issue filters support legacy aliases, while report queries use literal
  filters and restrict records to issues. CLI classification has its own eligibility
  query. Consolidating those policies is a separate behavior decision.
- CLI classification preserves evidence while updating its own field subset.
  Web editing accepts additional fields; service extraction must preserve both.
- Source URL validation checks all proposed values before individual writes; it
  does not provide a multi-document transaction.
- CSS is included in wheels via setuptools package data and loaded with
  `importlib.resources`, independently of the current working directory.

## Remaining Phases

1. Capture desktop/mobile and print baselines with representative, isolated data.
   Add characterization tests for web save operations before moving them.
2. Expand the tracking service to own listing, summary, save/delete and source
   aggregation operations. Introduce typed edit inputs to replace long positional
   argument lists. Leave notifications and dialog closure in the UI.
3. Share update persistence with CLI classification without changing prompts,
   evidence preservation, update subsets or date semantics.
4. Add `ui/app.py` for page composition, `ui/state.py` for client-local state and
   `ui/actions.py` for background UI adapters. Keep existing panel navigation.
5. Extract `ui/dialogs/issues.py`, then `ui/views/report.py`, followed by repo
   dialogs/dashboard and the issue view. Wire explicit callbacks rather than
   importing one view from another. Keep slots beside their owning tables.
6. Reduce `web.py` to its entry point and verify complete workflows. Preserve the
   duplicate-sync guard, timer/notification cleanup, button restoration, in-place
   chart-option updates, and separate state for two browser sessions.

Each extraction requires its focused tests before the next extraction begins.
No future-feature directories are created until they have an implementation.

## Verification

Run from the project root in the existing virtual environment:

```powershell
python -m unittest discover -s tests -v
python -m compileall -q src/labs_tracker tests
python -m labs_tracker.cli --help
python -m pip wheel . --no-deps --wheel-dir <temporary-directory>
```

The first slice expanded the passing suite from 24 to 41 tests. Checks cover CLI
contracts, helper/query behavior, progress/history, source validation, exports,
compatibility imports, package boundaries and stylesheet loading.

For packaging verification, install the wheel into a temporary location and load
the CSS from outside the source checkout. Verify the extracted stylesheet and moved
function bodies against the pre-refactor version, excluding incidental whitespace.

Browser acceptance remains required before restructuring the UI: dashboard counts,
repo edits, issue filters/history, source URL changes, report charts and row editing,
print preview, background success/failure cleanup and two-session isolation.
Use an isolated test database; never run destructive normalization against the
working database merely to validate a refactor. Automated tests use mocks/fakes and
temporary report directories, not live GitHub requests or the working database.