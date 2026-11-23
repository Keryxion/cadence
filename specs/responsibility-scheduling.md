# Responsibilities and triggers

## Why

An agent should be able to take ownership of work and keep moving it forward
between messages. A responsibility holds what it owns and what it has learned;
triggers give it opportunities to act. Both owner-assigned and agent-created
work are welcome. Every check runs in its own conversation, on that
conversation's model with its tools and memory.

The tools should help the agent get useful work underway within the owner's
bounds. Budgets bound execution and interruptions; temporary shortages leave
eligible work pending. Receipts explain what was accepted, adjusted or held and
what happens next. A refusal names the specific problem and how to correct it.
The agent must not need to invent relay wakes or repeatedly re-arm work to make
ordinary progress, and must not use those techniques to evade limits.

## Responsibility contract

A responsibility has a title, charter and persistent working notes. The charter
states what it owns and what good looks like. Notes carry progress and findings
between checks, compaction, new sessions in the same conversation and restarts.
It lasts until stopped by the owner or finished by the agent with a reason;
there is no automatic lifetime expiry. Owner-requested work has higher priority
than agent-created work; the contention policy is configurable rather than
fixed by this spec. The owner can inspect and stop either.

Each active responsibility has `min_per_24h` of at least one and `budget_per_24h`,
set at creation. The minimum cannot exceed the budget. The budget directly
configures the responsibility's token bucket: capacity is `budget_per_24h` tokens
and continuous refill is `budget_per_24h / 24` tokens per hour, capped at capacity.
The bucket starts full to permit concentrated initial work, then refill bounds
the sustained rate. For example, 30 gives a capacity of 30 and refill of 1.25
tokens per hour. This is a burst allowance and sustained rate, not a separate
hard count reset at a daily boundary; refill can permit more than 30 starts in
a particular 24-hour window. The supported budget must include at least 30
when the owner permits it. The agent may narrow its operating bounds but cannot lower an
owner-required minimum, raise an owner-permitted budget or widen other owner
limits.

The agent should explicitly schedule the next useful check. For daily work,
use a minimum of one and a trigger for an appropriate time, such as 9 a.m. in
the owner's timezone. For agent-paced work, set a new `at` trigger after each
check. Keeping the charter separate from timing lets the agent adjust its
approach without losing ownership or its notes.

The minimum is a fallback for neglected scheduling. It becomes active as soon
as the responsibility is active, without requiring a trigger. Treat its fallback
as a one-token bucket refilling continuously at `min_per_24h / 24` per hour.
Start it empty on activation. When full, a fallback is due; any started check
empties it, including a check started by another trigger. Pending checks do not
empty it. A long hold creates one overdue opportunity, not a catch-up burst.
There is no calendar boundary. A fallback turn prompts the agent to review the
work and fix its next scheduled time. Meeting the minimum alone does not
establish the intended schedule.

Only started checks count toward the minimum and spend responsibility tokens,
including silent or subsequently failed turns. With fewer than one token,
further work waits for refill. A missed minimum and its reason are visible;
the minimum never bypasses consent, availability, execution capacity or cost limits.

## `responsibility` tool

Calls are JSON objects with `action` and the fields allowed below. Unknown
fields and invalid combinations are rejected before any mutation. IDs and owner
identity come from the current conversation; there is no destination field.

| Action | Required fields | Optional fields | Effect |
|---|---|---|---|
| `create` | `title`, `charter`, `checks` | `notes`, `initial_at`, `owner_asked` | Create active work or a proposal if consent requires approval |
| `list` | None | `detailed` | List current responsibilities; detailed mode includes full records and finished history |
| `get` | `id` | None | Inspect one responsibility, its triggers and holds |
| `update` | `id`, at least one mutable field | `title`, `charter`, `notes`, `checks` | Atomically replace the supplied fields, retaining omitted fields |
| `pause` | `id` | None | Suspend triggers and the automatic minimum; record the pause visibly |
| `resume` | `id` | None | Resume paused work and its minimum backstop within all limits |
| `finish` | `id`, `reason` | None | End the responsibility as completed and cancel its pending checks and triggers |
| `delete` | `id` | None | Remove the responsibility from active work and cancel its triggers and pending checks |

Field types and validation:

- `id`, `title`, `charter`, `notes`, `reason`: strings; title, charter and reason
  must be nonempty when supplied. Titles allow 80 characters, charters 2,000,
  and notes 16,000. Notes default to empty; an update replaces
  them in full. Deleted and finished work retains an inspectable execution record.
- `checks`: object with required integer `min_per_24h` and `budget_per_24h`.
  Validate `1 <= min_per_24h <= budget_per_24h` against owner limits. Derive bucket
  capacity and refill from the budget; no separate bucket fields are accepted.
  An edit settles refill at the old rate up to the edit time, then applies the
  new capacity and rate. Raising the budget does not mint tokens; lowering it
  caps the current balance. Pause/resume does not reset the balance. Pause
  freezes the fallback clock; resume continues from the saved credit. Changing
  the minimum settles fallback credit at the old rate before applying the new one.
- `initial_at`: optional absolute timestamp or relative delay for the first
  opportunity. Without it, arrange an initial opportunity automatically.
- `owner_asked`: boolean, default false. A true value requires verified evidence
  of the owner's request; the agent cannot grant itself owner priority.
- `detailed`: boolean, default false. Nested objects reject unknown fields too.

Creation returns `id`, `status`, `armed`, `receipt` and the accepted record.
A proposal has `status: proposed`, `armed: false` and an approval instruction;
it consumes no execution capacity until approved by the owner. Updates return
the accepted record and any explicit adjustments. Inspection includes status,
charter, notes, provenance, limits, bucket balance, next fallback due time,
started checks, next opportunity, latest result, attached triggers and hold or
missed-minimum reasons. Compact lists put active entries first. Repeated finish,
delete or pause requests are safe and report the resulting state. Resuming a
finished or deleted item requires creating new work, not reviving its old queue.

```json
{"action":"create","title":"Release readiness","charter":"Keep track of release blockers and move them toward resolution.","checks":{"min_per_24h":1,"budget_per_24h":30},"owner_asked":true}
```

## `trigger` tool

A trigger states when work becomes eligible. Every trigger must contain an
explicit time or condition: this makes the intended schedule inspectable and
prevents unspecified timing from being mistaken for the user's request. A named
event such as gateway startup is an explicit condition. The daily minimum cannot
supply missing trigger fields.

| Action | Required fields | Optional fields | Effect |
|---|---|---|---|
| `create` | `when`; either `responsibility_id` or standalone `title` and `note` | `title`, `note`, `until`, `owner_asked` | Attach a trigger to a responsibility or create a standalone wake/watcher |
| `list` | None | `responsibility_id`, `detailed` | List this conversation's triggers, optionally filtered |
| `get` | `id` | None | Inspect the trigger, pending work and holds |
| `update` | `id`, at least one of `when`, `title`, `note`, `until` | None | Atomically replace supplied fields; `when` is replaced and validated in full |
| `pause` | `id` | None | Suspend this trigger while preserving pending work |
| `resume` | `id` | None | Resume within lifecycle and execution limits |
| `delete` | `id` | None | Cancel this trigger and its unstarted occurrences |

`id`, `responsibility_id`, `title` and `note` are strings. A responsibility ID
must refer to live work in this conversation and is immutable after creation.
An attached trigger inherits its charter; optional title/note add check-specific
context. A standalone trigger requires its own nonempty title and instruction.
`owner_asked` and `detailed` are booleans with the same verification and default
rules as above. Owner priority on a responsibility comes from its own provenance.
`until` has optional `expires` (timestamp), `max_fires` (positive integer started
turns), and `owner_replies` (boolean cancellation condition). Omitted lifecycle
fields use the owner's configured wake/watcher bounds. Unknown fields are
rejected; responses use the same ID, status, receipt and inspection conventions
as responsibilities, with `next_due_at` or the event condition and any deadline.

`when` is an object with `kind` and the fields below. Fields marked optional
may be omitted; all other listed fields are required. Time expressions are
resolved to absolute UTC instants in receipts using the configured timezone.
Durations are positive strings such as `20m` or `2h`.

| `kind` | Fields | Activation condition |
|---|---|---|
| `at` | `at`: timestamp or relative delay | Once at the specified time |
| `every` | `every`: duration; optional `at`: local HH:MM | Recurring interval, optionally anchored to local time |
| `cron` | `cron`: expression | Cron schedule in the configured timezone |
| `owner_silent` | `after`: duration | Once per episode of owner silence lasting that long |
| `file` | `path`: string; optional `pattern`: regex | File changes, or an appended line matches the pattern |
| `process` | `pid`: positive integer | Process exits; check creation time to avoid PID reuse |
| `url` | `url`: HTTP(S) URL; optional `pattern`: regex | Response changes, or matches the pattern |
| `command` | `command`: string argv array; optional `cwd`: path, `fire_on`: `change`, `success`, `failure` or `json` (default `change`) | Read-only allowlisted command output changes, succeeds, fails, or returns a structured fire decision |
| `startup` | None | New gateway process starts after arming, including after host reboot |
| `kanban_completed` | Optional `task_id`, `board`: strings | Matching task completes |
| `kanban_blocked` | Optional `task_id`, `board`: strings | Matching task becomes blocked |
| `kanban_worker_exited` | Optional `task_id`, `board`: strings | Matching worker exits |
| `subagent_done` | None | Subagent finishes |
| `api_error` | None | Provider API error, aggregated with cooldown |
| `reaction` | Optional `emojis`: string array | Reaction in this conversation matches the filter, or any reaction if omitted |
| `message_edited` | None | Message edited in this conversation |

Probe types (`file`, `process`, `url`, `command`) also accept `check_every`, a
positive polling duration within owner source limits. Probe and event watchers
can accept a `deadline` timestamp for one "nothing happened" activation when no
match arrived; that activation does not imply success or end the watcher.
Probe errors/timeouts do not count as matches. Startup uses its process event
condition alone. Plugin reloads and scheduler restarts do not count as startups.
Only human activity resets an owner-silence episode.

Triggers for the same responsibility may coexist. Repeated pending matches
coalesce rather than creating a catch-up burst. At admission, list every contributing trigger
ID and kind in the wake, including each trigger's instruction if supplied. Mark a
due fallback separately (it need not have a trigger ID). One coalesced start
spends one global and one responsibility token, not one per match. Each included
trigger counts that start once toward its own `max_fires`. Matches arriving after
admission stay pending for a later check. A recurring interval expresses
that trigger's opportunities; it does not impose minimum spacing on checks from
other triggers. Pausing/deleting a trigger does not stop the responsibility's
minimum backstop; pause/delete the responsibility to stop all of its work.
Edits or deletion cannot undo a turn that has already started; the receipt says
when that is the case. Supporting triggers remain subject to active-item and
per-turn child limits without accumulating depth just for continuing ownership.

```json
{"action":"create","responsibility_id":"r_example","when":{"kind":"every","every":"1d","at":"09:00"}}
```

## Bounded execution

Owner-requested standalone reminders retain owner reminder treatment for
notifications and cost. An agent change to their instructions or timing revokes
that exemption; owner-requested responsibilities still use responsibility budgets.
All started turns require global execution capacity.

Execution and notifications have separate budgets because useful work can be
silent and a quiet owner should not prevent preparation or progress.

| Control | Rule |
|---|---|
| Global execution bucket | Every agent-initiated turn consumes one token when it starts |
| Per-responsibility bucket | Capacity `budget_per_24h`, refill `budget_per_24h / 24` per hour; a check consumes one token when it starts |
| Global notification bucket | Controls delivered user interruptions independently of execution |
| Owner cost limit | Independently bounds spend on agent-initiated work |

Admit both required execution tokens together; never spend one without the
other. Pending or refused injections consume no tokens and do not satisfy the minimum.
If either bucket lacks capacity, eligible work waits and all limits are checked
again before starting. One responsibility's empty bucket does not block another
with capacity. Refill never exceeds capacity; global execution defaults are capacity 30 and refill 1.25 per hour, configurable
by the owner. Global means all conversations served within the same Hermes
profile. Notification defaults are capacity 15 and refill 12 per hour. Cancellation or expiry of deferred work is visible.

Notification holds and unanswered-message limits hold messages while eligible
responsibility checks can run silently and keep findings in notes. Quiet checks
alone never pause a responsibility or add recurring interval floors, wake spacing
or no-change slowdown. The agent chooses its next useful check within the
minimum, buckets and owner limits. Error backoff and safety stops still apply.

Consent, emergency stop, provider availability, cost and busy state are checked
before a turn starts. At most one scheduled turn is in flight per conversation.
Tools cannot choose another destination, modify owner settings or grant consent.
Gateway DMs are supported; recognized groups require the owner to disable DM-only
mode. CLI, TUI, Desktop, API-server, cron and unknown chat types cannot arm work.
IDs from another conversation reveal nothing and permit no mutation.

State, claims and accounting are durable and isolated by profile/conversation.
Restarts, clock changes and competing schedulers cannot duplicate starts;
interrupted started turns are recorded, not blindly rerun. Late one-shots outside
the catch-up window are visibly missed. Bounded retries and backoff expose
persistent errors. Probes honor read restrictions, argv allowlists, sanitized
environments, bounded untrusted payloads and network destination restrictions;
source content cannot grant consent or authorize unbounded work.

## Visibility and acceptance

A compact desk view opens responsibility turns and is available to the owner:
charters, latest work, next opportunities, started checks against the minimum,
bucket/notification holds, missed minimums and available usage/cost. The model
starts with fresh saved state; no conversion of previously scheduled work is
required. WebSocket sources are outside this implementation.

Verify the action and field tables, all trigger types and these interactions:

- Cross midnight with no token and pending work: only elapsed refill can admit
  it. Restart while a timer and an event for the same responsibility are held;
  on refill, admit one wake listing both triggers (and the fallback if due),
  preserving their instructions and charging each execution bucket only once.

- Daily work at 9 a.m. has a minimum of one and an explicit timed trigger. If the
  agent forgets the next schedule, the adaptive minimum prompts it to fix it.
- Minimum scheduling begins on activation, including owner approval of a proposal;
  pending triggers never satisfy it, and blocked minimums remain visible.
- Creation, inspection, edits and removal preserve conversation isolation. Notes
  survive new sessions; finishing or deleting cancels attached pending work.
- With `budget_per_24h: 30`, derive a full 30-token bucket and refill of 1.25 tokens
  per hour. Reject independent bucket fields. Editing the budget changes both
  capacity and refill without minting tokens; no daily boundary resets it.
- Silent started checks consume both execution tokens and count toward the minimum;
  pending work consumes none. Exhaust either bucket, then refill: work waits and
  starts only when both tokens and all guardrails permit it.
- Exhaust one responsibility's bucket while another can run. Exhaust notification
  capacity while checks can still make silent progress. Exhaust responsibility
  tokens or reach a cost boundary without bypassing either to satisfy the minimum.
- Reject invalid/missing trigger conditions atomically with corrective feedback;
  preserve pending work on temporary holds; do not duplicate starts after edits,
  restarts, competing claims or repeated event matches.
