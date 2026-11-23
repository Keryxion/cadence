# Cadence

Cadence gives a Hermes agent time to own work between messages. A responsibility
holds its charter and persistent notes; explicit time or event triggers give it
opportunities to act. Useful work can be silent. The owner controls execution,
interruptions, consent and spend.

Every check runs in the messaging-gateway conversation that armed it, using its
model, tools and memory. Cadence does not use hidden side models or choose another
conversation as a scheduling destination. DMs are supported; gateway groups need
`dm_only: false`. CLI, TUI, Desktop, API-server and cron sessions cannot arm work.

## Set up

Install this standalone plugin through Hermes, enable it in your profile, and
explicitly permit gateway injection:

```yaml
plugins:
  entries:
    cadence:
      enabled: true
      allow_gateway_injection: true
      settings:
        enabled: true
        agent_can_create: "yes"
        execution_capacity: 30
        execution_refill_per_hour: 1.25
        responsibility_budget_max: 120
        interruptions:
          capacity: 15
          initial: 15
          refill_per_hour: 12
```

`agent_can_create: ask_first` creates proposals that the owner approves with
`/cadence approve <id>`. `no` disables agent creation. Tools cannot change these
settings or grant consent. Own time is off by default; `own_time_hours` enables
regular opportunities to reflect, consolidate memory, investigate or rest.

This model uses fresh state in `<profile>/plugin-data/cadence/cadence.db` and does
not import saved work from another state database. No data migration is required.
WebSocket sources are outside this implementation.

## Responsibilities and triggers

Ask your agent to own something: “Keep track of release readiness; check daily
at 9 a.m. and investigate anything that blocks us.” It uses `responsibility`:

```json
{"action":"create","title":"Release readiness","charter":"Track blockers and move the release toward readiness.","checks":{"min_per_24h":1,"budget_per_24h":30},"owner_asked":true}
```

Then it attaches a `trigger` using the returned ID:

```json
{"action":"create","responsibility_id":"r_example","when":{"kind":"every","every":"1d","at":"09:00"}}
```

The minimum is an elapsed-time fallback if scheduling is neglected: it prompts
the agent to review the work and repair its next schedule. The budget configures
the responsibility's token bucket directly. A budget of 30 means capacity 30,
initially full, with refill of 1.25 tokens per hour. This permits a burst and
bounds the sustained rate; it is not a hard calendar-day quota. It can be at
least 30 when the owner permits it, subject to `responsibility_budget_max`.

Each started responsibility check spends one responsibility token and one global
execution token. Every other agent-initiated turn also needs a global execution
token. Queued work reserves capacity but spends nothing until it starts. Empty
buckets defer eligible work. Restarts preserve balances and pending work.

Multiple triggers for a responsibility share one check listing every contributing
reason and instruction. A timer, event and fallback do not create three competing
turns. Quiet work never automatically pauses a responsibility. Notes and ownership
survive new sessions in the same conversation.

Available trigger conditions:

| Category | Kinds |
|---|---|
| Time | `at`, `every` (optional local-time anchor), `cron` |
| Human activity | `owner_silent`, `reaction` (optional emoji filter), `message_edited` |
| Deterministic observation | `file`, `process`, `url`, `command` |
| Gateway and Hermes events | `startup`, `kanban_completed`, `kanban_blocked`, `kanban_worker_exited`, `subagent_done`, `api_error` |

Every trigger specifies a time or condition. For agent-paced work, set the next
`at` after each check. Watchers evaluate conditions without model calls and can
have a deadline reporting that nothing happened. Errors are never changes or
success. A standalone trigger needs its own title and instruction instead of a
responsibility ID.

Standalone triggers use the owner's lifetime bounds: `max_lifetime_days` is
14 by default and `max_reminder_days` allows owner-requested one-time reminders
up to 365 days ahead. Receipts report adjusted timing and expiry.

## Tools and owner controls

`responsibility` and `trigger` each support creation, listing, inspection, edits,
pause, resume and deletion. Responsibilities also support explicit completion
with a reason. `respond` records the running check's result and notification
decision; `follow_up` offers short continuations of owner work. `get_time` reads
the clock and `request` communicates with self-named conversations in the profile.
See the [responsibility and trigger contract](specs/responsibility-scheduling.md),
[results contract](specs/respond.md), and [continuation contract](specs/follow-up.md).

| Owner command | Purpose |
|---|---|
| `/cadence status`, `desk`, `list` | Scheduler, responsibilities, budgets and holds |
| `/cadence why <id>` | Inspect a responsibility or trigger and its next eligibility |
| `/cadence approve <id>` | Approve proposed work |
| `/cadence pause <id>`, `resume <id>`, `delete <id>` | Control work |
| `/cadence budget <id> <minimum> <budget>` | Set a responsibility's checks and refill budget |
| `/cadence off`, `on` | Disable or enable this conversation |
| `/cadence responsibility <JSON>`, `trigger <JSON>` | Owner access to the full management contract |
| `/cadence name <name>` | Opt this conversation into named communication |

Receipts say what is armed, proposed or held. A host queue receipt is not proof
of execution or delivery. Inspect shows the binding hold and next eligible time
when calculable. Commands do not count as answering an unanswered agent message.

## Cost, attention and safety

A check is a normal billed model turn with the conversation's full context.
Silent work consumes execution capacity. Notifications have an independent
profile-wide token bucket and unanswered-message holds; lack of notification
capacity lets responsibility work continue silently with findings retained.
`daily_cost_limit_usd` bounds priced agent-initiated spend when configured.
Emergency stop, consent, provider backoff and busy-chat checks apply before starts.
At most one scheduled turn runs in a conversation at a time.

Disclosure — wakes, watchers, responsibilities and own-time turns run full turns
on the conversation's own model, billed like any message; own time is off by
default; command probes run allowlisted read-only commands without an approval
prompt; url probes make GET requests you configured; state stays in the profile's
plugin-data; no telemetry.

The argv guard is not a sandbox: allowlisted programs and local configuration
must be trusted and read-only. Model wake turns retain the conversation's tools
and permissions. GET requests include the configured URL, including its query;
URL userinfo, cookies, Authorization headers and ambient proxies are refused or
unused by the probe. Command probes use Hermes' sanitizer on an allowlisted
environment, without provider, bot or GitHub tokens; gh uses its own hosts.yml
or keyring. URL probes always block cloud metadata and block private/local
addresses unless url_allow_private is enabled, checking each hop at connect
time. File probes honor Hermes read blocks at arm/update and every check,
including rotation. Helpers run in the watcher's profile scope. Existing git/gh
credentials and remote configuration can be used by command probes.
gh -R HOST/... and git ls-remote <url> can reach any host the machine can reach.
The command watcher's allowlisted environment does not pass proxy or custom-CA variables yet.
The plugin adds no telemetry; Hermes, model providers and configured endpoints
retain their own data handling. Notes, summaries and payloads are local plaintext.
See [SECURITY.md](SECURITY.md) for the detailed boundaries and report vulnerabilities
privately through the repository's security advisory form.

## Known delivery limits

Signal/SimpleX messages queued while the model is busy and Codex app-server
native steer can omit the human-origin evidence Cadence needs to recognize an
owner reply. Gateway commands sent mid-turn can be dropped by Hermes; inspect
the reply before assuming a stop or approval succeeded. Provider failures may
show Hermes's own failure notice even for silent work. These host limitations
do not authorize retries that duplicate work or bypass consent.

Only priced calls contribute to monetary estimates; unpriced routes are counted
separately and can still incur provider charges. Token and cost estimates are
observations, not a provider invoice.

## Development

```bash
python -m pip install pytest pyyaml croniter psutil
python -m pytest -q
```

Unit tests deny network access and billed APIs. CI separately runs pinned Hermes
loader tests and gateway E2E on loopback. Diagnose deployments with status and
logs; never fire a wake or change consent to reproduce a bug.

Apache-2.0. Built for Hermes Agent.
