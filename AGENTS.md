# AGENTS.md

Guidance for AI coding agents, and for people, working in this repository.

## What this is

Cadence is a standalone Hermes Agent plugin for bounded wakes and deterministic watchers. It schedules a turn in the messaging-gateway conversation that armed it, using that conversation's model and tools. The current release delivers into gateway DMs (group chats only when `dm_only` is off); CLI, TUI, Desktop, API server and cron arming are refused.

## Layout

- `plugin.yaml`: manifest, compatibility and settings schema.
- `__init__.py` and `cadence/registration.py`: plugin loading, hooks and profile runtime.
- `cadence/`: scheduler, policy, commands, probes and SQLite store.
- `skills/cadence-usage/SKILL.md`: bundled usage guidance; `skills/cadence-report-problem/SKILL.md`: the bug-report workflow.
- `tests/`: network-denied unit tests and separate integration/E2E suites.
- `bench/`: deterministic simulation and separately operated live benchmarks.
- `.github/workflows/`: unit matrix, pinned-Hermes loader and gateway E2E CI.
- `SECURITY.md`: consent, session, probe and data-handling boundaries.

## Setup and checks

CI is `.github/workflows/ci.yml` (unit suite and Hermes integration) and `.github/workflows/e2e.yml` (real gateways on loopback).
The unit suite runs locally in about two minutes:

```bash
python -m pip install pytest pyyaml croniter psutil
python -m pytest -q
```

The integration and gateway E2E jobs install pinned Hermes and run `tests/integration` and the E2E harness. Leave those to CI unless
your change touches them.

## Rules

- Keep each change small and focused: one change per PR.
- Don't bump versions, create tags, or add CHANGELOG release headings. Maintainers cut releases.
- No build step or committed bundles: this plugin ships Python source and its manifest.
- Unit tests must not access the network or billed model APIs; preserve the network-denial fixture.
- Keep consent, destination/session isolation, caps and silent-response boundaries intact.
- Diagnose installed deployments with status and logs only; do not fire a wake, send a DM or change consent to reproduce a bug.
- Never commit secrets, tokens, real user data, or machine-specific paths.
- Tests use a temporary `HERMES_HOME`, never a real one.

## Filing issues

- Search first: `gh issue list -R Keryxion/cadence --state all --search "<key words>"`.
- Use the bug form headings: What happened, What you expected, Steps to reproduce, Plugin version, Hermes version, Where it happened, Operating system, Diagnostics, Relevant log lines.
- Maintainers filing from the CLI always pass labels: `--label bug,triage-pending` (or `triaged` once triaged), plus `agent-drafted` when an agent wrote it.

## Security

Report vulnerabilities privately: https://github.com/Keryxion/cadence/security/advisories/new

## Shared with other repos

These files have copies or dependents in other Keryxion repositories; a change here also belongs there.

- `.github/workflows/alpha.yml` and `.crow/alpha.yaml` are the same deploy pipeline as Keryxion/hermes-converse's: a deploy fix here is needed there.
