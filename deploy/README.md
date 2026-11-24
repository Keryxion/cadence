# Cadence alpha delivery

`alpha:sakura`, `alpha:penny` and `alpha:hermie` on a same-repository PR select
that Hermes host. Adding a label, pushing while labeled, or reopening creates a
GitHub deployment of the PR **head SHA**, environment `sakura`, `penny` or `hermie`.
Removing a label stops future requests; it does not cancel queued work or restore
the host. Multiple labels deploy to multiple hosts. There is no test gate here
(`required_contexts: []`); label only trusted code that is ready to execute.

The workflow runs base-branch `pull_request_target` code without checking out PR
code. Forks are refused. Crow receives the deployment webhook and runs
`.crow/alpha.yaml` with `skip_clone`, SSHing `deploy <40-hex SHA>` with a restricted
key. Same-repository PR authors are trusted: Crow's pipeline configuration and
all deployed Python are executable code. This is not a sandbox for untrusted PRs.

The independently installed forced command locks the plugin checkout, refuses
local changes, fetches the exact SHA, detaches HEAD, and restarts the system
`hermes-gateway` service. It rolls the code back and restarts again if restart or
Cadence readiness fails; a failed rollback is explicitly reported. The command
returns failure even after a successful rollback. Deploys are serialized, not
ordered by PR age: a queued older SHA can still deploy later. The log is
`~/.hermes/plugins/cadence/.git/alpha-deploy.log`.

Manifest changes deploy with the source. Dependencies are not installed by the
deploy script; install any new dependencies separately. Rollback restores source
only, not SQLite data or external effects; do not alpha-deploy incompatible data
migrations. Restarting the gateway affects all its plugins and conversations.

## Cadence readiness

No Converse HTTP route or generic gateway endpoint is used. The separately
installed `cadence-alpha-health` reads the existing default profile's
`~/.hermes/plugin-data/cadence/pulse.db` using read-only SQLite queries; it does not
load Cadence, create a runtime, arm a wake, or send a message. It requires:

- A live system service MainPID matching Cadence's recorded `poller_pid` and a
  nonempty poller epoch.
- `poller_started_at` at or after this restart, a heartbeat at most 15 seconds old,
  no recorded tick/settings error, no in-progress probes, and a held poller lock.
- Two healthy samples with advancing heartbeat, within about two minutes.

This verifies a running Cadence poller, not model delivery or every watcher.
It uses the existing `Runtime`/`Poller` metadata contract, which must remain
compatible with the installed helper. No new runtime endpoint is introduced.

## Setup (not performed by this PR)

Infra configuration and the first deployment require separate approval. Nothing
here creates labels, secrets, SSH keys, sudo permissions or a host installation.

1. Enable Crow for `Keryxion/cadence`, including GitHub deployment webhooks and
   permission to run deployment pipelines; confirm its deployment target and SHA
   variables match `CI_PIPELINE_DEPLOY_TARGET` and `CI_COMMIT_SHA`.
2. Create the three labels. The Actions workflow must be on the PR base branch
   before labeling can use it. Configure repository/environment authorization as
   appropriate. GitHub deployments are requests, not evidence of host readiness;
   consult Crow logs/exit status. Status publication depends on Crow integration.
3. Add **Cadence-specific** Crow secrets, permitted for event `deployment`:
   `alpha_ssh_key`, `alpha_ssh_config`, `alpha_known_hosts`. Do not reuse Converse's
   deployment key. SSH config aliases `sakura`, `penny`, `hermie` must specify the
   verified host address, `User hermes`, `IdentityFile ~/.ssh/alpha`,
   `IdentitiesOnly yes`, and `StrictHostKeyChecking yes`. Pin verified host keys.
4. Each Linux host needs Bash, git, flock, Python 3 with SQLite, and an existing
   clean, standalone clone at `~/.hermes/plugins/cadence`, origin
   `Keryxion/cadence`, with credentials to fetch private PR commits. The system
   `hermes-gateway` must run as this user with its MainPID owning Cadence's poller.
   Alternate plugin paths, linked worktrees, user services, child-process pollers
   and non-default profile data paths are not supported by this minimal script.
5. Install `deploy/cadence-alpha` and `deploy/cadence-alpha-health` as executable
   `~/.local/bin/cadence-alpha` and `~/.local/bin/cadence-alpha-health`, outside the
   deployed checkout. Reinstall after reviewed helper changes. Restrict the key
   in `authorized_keys` with
   `restrict,command="/home/hermes/.local/bin/cadence-alpha" <public key>`.
   Permit only the exact noninteractive sudo systemctl restart/show commands
   used by the script; no unrestricted sudo or arbitrary shell access.
6. **Missing host readiness prerequisites must be checked per host before labeling:**
   Cadence is installed/enabled, dependencies already available, the default
   profile is actually served by the gateway, and gateway injection consent is
   explicitly enabled. An unserved/non-consenting profile will never start its
   poller and will fail readiness; do not change consent automatically. Verify
   the helper against the existing poller with the service's current MainPID and
   `0` as its second argument. This PR has not inspected or changed those hosts.

Reference pattern: the four Converse alpha files at
`Keryxion/hermes-converse` commit `a4732709b81da3d68694e296ec08b98c9c262db4`.
Cadence adds strict full-command validation, dirty-check guard, rollback on
restart failure, and its own poller health check rather than Converse's route.

## Local checks

`python -m pytest tests/test_alpha_delivery.py -q` exercises validation,
preflight, success, health and restart failure, rollback failure, and the workflow
trust boundary. Git, sudo/systemctl, sleep, lock command and deployment health
are mocked for script tests; separate helper tests use temporary SQLite state
and real local file locks. No host SSH, installs, real restarts or network calls
are made by these tests. Live end-to-end deployment remains unverified until
separately approved infra setup and a supervised first deployment.
