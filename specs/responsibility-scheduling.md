# Responsibilities and scheduling

## Purpose

Cadence gives an agent time in its own conversation to own standing work,
respond to events, follow a question, or think something through without waiting
for another message. Every wake is a normal turn on that conversation's model,
with its tools and memory. There are no hidden side models deciding what the
agent should do.

The `responsibility` tool manages standing charters and their working notes.
The separate `trigger` tool schedules the next run by time or activates work
from an event. `follow_up` provides a short continuation of work already underway.
`request` handles conversation-to-conversation communication; it does not
schedule work in another conversation directly.

This specification describes the required behavior at merge. Its acceptance
cases are requirements for that behavior.

## Responsibilities

A responsibility has a title, a general charter describing what it owns and
what good looks like, and persistent working notes. The agent can inspect and
refine its charter, record progress, and carry findings forward between checks.
A responsibility survives compaction, a new session in the same conversation,
and gateway restarts. It has no automatic lifetime expiry: it lasts until the
owner removes it or the agent finishes it and records why.

The `responsibility` tool can create, inspect, edit and delete responsibilities,
record check results and update working notes. The owner can stop any
responsibility. Listing returns compact current entries with active work first,
next-check timestamps, latest results and hold reasons; detailed inspection also
provides full records and finished history.

Responsibilities may be requested by the owner or created proactively by the
agent; both are welcome. Owner-requested responsibilities have higher priority.
The priority policy for scheduling, contention and resource allocation is not
prescribed here. Priority does not exclude agent-created responsibilities or
bypass any limit. The owner is told when the agent takes on a responsibility,
what it owns, and how to stop it. Where owner approval is required, creation is
a proposal and no work starts until approval.

Creating an active responsibility immediately enables its automatic minimum
backstop. The agent should use an explicit trigger to express the intended next
check time. For "check on this daily," a minimum of one check per 24 hours is
appropriate, alongside a trigger for a useful time such as 9 a.m. in the owner's
timezone. The minimum provides a fallback if the agent forgets to schedule the
next check; the fallback turn prompts it to review the responsibility and fix
the next scheduled time. The agent can
also create supporting wakes and watchers during a responsibility check,
within the owner's active-item and per-turn child
limits. A standing responsibility does not accumulate wake-chain depth merely
by continuing to exist. Supporting work follows its own consent and lifecycle
rules; it cannot evade limits through repeated re-arming.

## Daily checks and the adaptive minimum

Each responsibility has a minimum and maximum number of checks per 24-hour
period, set at creation within the owner's limits. References to a day or daily
limits in this specification mean that 24-hour accounting period. The minimum
is at least one and cannot exceed the maximum. The automatic minimum backstop
begins as soon as the responsibility becomes active, including after approval
when creation requires it; it does not wait for the agent to create a trigger.
The supported maximum includes at least 30 checks per day when the owner
permits it. The owner can change these limits; the agent can tighten its own
limits but cannot widen the owner's.

A check is a full model turn for the responsibility. It counts toward both the
minimum and maximum when it starts, whether it makes silent progress, reports
a finding, finds nothing to do, or subsequently fails. Pending or deferred work
is not a check and does not count toward either daily limit. Once the maximum
is reached, further checks wait until the next daily period.

The minimum provides an adaptive automatic backstop. Cadence calculates the
next automatic opportunity from the time remaining in the day and the remaining
minimum wakeups. As triggered checks start, the backstop adapts to the reduced
number still needed. It is not a fixed-interval heartbeat. Pending triggers do
not satisfy the minimum or stand in for checks that have started.
The agent uses a backstop turn to do any useful work due and ensure that the
next explicit trigger is set appropriately. Meeting the minimum alone does not
establish the intended time of day for future checks.

An initial check time may be supplied at creation. Without one, Cadence arranges
an initial opportunity without requiring a separate schedule. After a check,
the agent should use `trigger` to arrange the next useful opportunity. The adaptive
backstop operates alongside those triggers, within the daily maximum.

A due time is an opportunity, not a delivery guarantee. Execution tokens,
responsibility tokens, busy or offline conversations, consent, emergency stop,
provider availability and the owner's cost limit can delay or prevent a check.
A missed minimum is visible to the owner with the reason; it never authorizes
bypassing a constraint or a burst of overdue checks.

## Execution, responsibility and notification budgets

Cadence uses three independent token-bucket controls:

| Bucket | Scope | Token consumed |
|---|---|---|
| Execution | Global agent-turn starts | One for every agent-initiated turn when it starts, including silent checks and continuations |
| Responsibility | One responsibility | One when a check for that responsibility starts |
| Notification | Global user interruptions | For a delivered interruption, independently of turn execution |

A responsibility check starts only when both its own bucket and the global
execution bucket have a token and all other limits and guardrails permit it.
Starting consumes one token from each execution bucket and increments the daily
check count. Admission must reserve both tokens together: failure to obtain one
must not spend the other. Pending, queued or refused injections consume neither
execution token and do not increment daily check counts.

If either execution bucket lacks a token, eligible triggered work remains
pending until capacity is available, rather than being discarded. On retry,
Cadence evaluates the daily maximum and every other applicable guardrail again.
Exhausting one responsibility's bucket does not prevent another responsibility
with tokens from using available global execution capacity. Deferred work can
still end through cancellation, expiry or another lifecycle rule; its disposition
must be visible.

Each responsibility's burst capacity and ongoing refill rate are configured at
creation within the owner's limits. Its bucket starts full and supports a large
initial capacity for concentrated work before refill paces subsequent checks.
Refill never raises the balance above capacity. No numeric bucket capacities or
refill defaults are prescribed here.

The owner's cost limit independently bounds spend on agent-initiated work. It
is distinct from all three buckets and from daily responsibility limits. The
agent cannot widen it. Each started turn and its available usage and cost data
are recorded, including silent work.

## Silent work and notifications

A check can research, write files, maintain notes or prepare something without
sending a message. Silent progress is useful work and consumes execution capacity.
It does not consume a notification token merely by running.

The agent records a structured result with an outcome, a summary, updated notes
and an explicit notification decision. Outcomes distinguish useful progress,
nothing to do, completion, blockage and a need for owner attention. Completion
ends the responsibility with a reason; silence or a quiet check does not.
Results must belong to the check running in that conversation, and failed turns
must not commit an uncompleted notes or scheduling update as successful work.

The agent notifies only when useful, with a short message leading with the
result or question. It must not guilt, pester or repeatedly repeat itself.
An empty notification bucket or an unanswered-message hold does not prevent an
otherwise eligible responsibility check. The check runs silently and retains
anything worth reporting in its notes. Daily check allowances never authorize
an interruption. Human activity clears the unanswered hold; agent turns and bot
messages do not count as owner replies.

A silent check suppresses its final reply through the gateway's structured
silence handling. The agent does not type a sentinel or emit commentary alongside
tool calls that would expose a supposedly silent check. Duplicate summaries do
not become repeated notifications. Requested short continuations do not consume
notification tokens merely by resuming work.

Responsibility pacing is controlled by triggers, the adaptive daily minimum,
the daily maximum and the two execution buckets. No additional recurring
interval floor, pacing bound, wake spacing or automatic no-change slowdown is
required for a responsibility. Repeated quiet checks do not automatically pause
it; the agent can choose a later next check. Error backoff and safety stops still
apply.

## Triggers and supporting work

The `trigger` tool schedules a responsibility's next run by time or activates it
from an event. Every trigger must specify an explicit time or condition that
determines when it becomes eligible to run. Creation or editing without either
is refused. The responsibility's automatic minimum backstop does not satisfy
this requirement for a trigger.

The following trigger types are supported for responsibility checks and
supporting work:

| Type | Explicit time or condition |
|---|---|
| `at` | A one-time absolute timestamp or relative delay; local time expressions use the configured timezone |
| `every` | A recurring duration, optionally anchored to a local time such as 9 a.m. |
| `cron` | A cron expression evaluated in the configured timezone |
| `self` | An agent-chosen explicit next time or delay, which the agent can revise after each check |
| `owner_silent` | A specified duration without an owner message; at most one activation per silence episode |
| `file` | A configured file changes, or an appended line matches a specified pattern |
| `process` | A specified process exits, with process identity checked to avoid PID-reuse mistakes |
| `url` | A configured web response changes or matches a specified pattern |
| `command` | A configured allowlisted read-only command changes output, succeeds, fails, or returns a structured fire decision |
| `startup` | The next gateway process startup after arming, including startup after a host reboot |
| `kanban_completed` | A kanban task completes, optionally filtered by task or board |
| `kanban_blocked` | A kanban task becomes blocked, optionally filtered by task or board |
| `kanban_worker_exited` | A kanban worker exits, optionally filtered by task or board |
| `subagent_done` | A subagent finishes |
| `api_error` | A provider API error event occurs, with aggregation and cooldown to avoid an error flood |
| `reaction` | A reaction occurs in the owning conversation, optionally filtered by emoji |
| `message_edited` | A message is edited in the owning conversation |
| WebSocket event | A specified event condition on a configured WebSocket connection is met |

Selecting a named event such as `startup` or `subagent_done` is itself an
explicit condition; no extra timestamp is required. A source address alone is
not a condition: a watcher must specify what activates it, either through its
type's defined condition or an explicit match rule. `self` requires an explicit
next time or delay; the daily minimum cannot supply an omitted trigger time.
Detailed tool schemas and WebSocket source behavior are not prescribed here.

Time triggers support one-time and recurring work. A recurring trigger schedules
opportunities within the responsibility's limits; its interval does not become
an additional minimum-spacing constraint on checks activated by other triggers.
The agent can revise its next useful check time without changing the owner's
daily limits.

Owner-silence episodes run from one human message to the next. Agent turns, bot
replies and internal events do not reset them. Startup triggers fire for a new
gateway process, not a plugin reload or scheduler-thread restart in that process.
They can be limited to one activation or remain active for later startups within
their configured lifecycle limits.

Probe and event watchers support an optional explicit deadline as a one-time
fallback when no matching event has occurred by that time. A deadline activation
says that nothing happened; it must not imply success. The watcher can continue
after that activation until its lifecycle ends. Source failures and timeouts
are errors, not evidence that a condition matched. Probe polling intervals
control deterministic source evaluation, not mandatory spacing between model
checks for a responsibility.

Triggered checks use the same daily counts, execution buckets, cost limits,
consent and conversation boundaries as automatic checks. A pending event or due
time does not consume capacity or satisfy the adaptive minimum.

Cadence also supports time-based wakes and reminders, deterministic watchers,
and own time. A watcher evaluates its configured condition without a model call
and starts a turn only when there is something to act on. Sources include files,
processes, web resources, allowlisted read-only commands and Hermes events.
Supporting work has its own cancellation, expiry, active-item and error limits;
responsibility daily counts apply only when a responsibility check starts.
Every agent-initiated turn consumes a global execution token, including work
started by a watcher or own-time opportunity.

Owner-requested reminders are identified as such and are not muted as unanswered
agent outreach. Their receipts distinguish confirmed scheduling from proposals
and state timing, holds and expiry truthfully. A host queue receipt proves queue
acceptance, not that a turn started or a message was delivered.

Own time is settings-controlled and off by default. When enabled, it offers the
agent time to reflect, consolidate memory, work on responsibilities, follow a
question or rest. Its timing is cache-aware. The owner controls enabling and
stopping it; the agent may adjust timing within the owner's bounds. It has no
automatic lifetime expiry. A silent useful turn is recorded as progress.

`request` is a separate communication facility. Scheduled work always belongs
to the conversation that armed it and fires there. Asking another conversation
to take something on does not itself create a schedule there: the recipient
must accept and arrange its own work with its own tools and permissions.

## Short continuations

`follow_up` gives the agent one further opportunity to act on the current
conversation, including any intervening messages. It is neither a responsibility
check nor a notification. Only a verified owner turn or one of its continuations
may arm it. Each call creates an independent timer; replacing one requires
cancelling its ID explicitly.

The tool accepts a relative delay from 15 seconds through 15 minutes inclusive,
or a timer ID to cancel. Arming returns an ID and an absolute UTC due timestamp.
Cancellation is scoped to this conversation, is safe to repeat, and reports if
the timer already started. Timers retain their originating chat, session and
turn identity, survive gateway restarts, and are orphaned by a new session so
that they cannot resume work there.

On firing, the continuation receives the scheduled and current timestamps and
the current conversation history. It may arm another continuation. If the chat
already has a turn underway when the timer becomes due, the timer is consumed
without queuing another turn. Otherwise its start requires a global execution
token and the applicable consent, availability and cost checks. It does not
consume a responsibility token or count toward a responsibility's daily limits.

## Conversation, consent and delivery boundaries

- Work runs in the messaging-gateway conversation that armed it, on that
  conversation's model and tools. Scheduling and responsibility tools have no
  destination parameter. IDs from another conversation cannot reveal or change
  its records. Profile state and configuration are isolated.
- Arming requires plugin enablement, gateway injection consent and session
  consent. Agent creation policy can forbid creation or require owner approval.
  Tools report refusals and clamps and cannot write settings or grant consent.
- Messaging DMs are supported. Recognized gateway groups require the owner to
  disable the DM-only restriction. Unknown chat types and CLI, TUI, Desktop,
  API-server and cron arming are refused with a clear reason.
- Emergency stop, provider unavailability and a busy conversation block starts
  before a model call. There is at most one scheduled turn in flight per
  conversation. A responsibility's new session binding follows that conversation;
  it never retargets another chat.
- Deadlines, triggers, pending occurrences, notes and accounting are durable.
  Restarts, sleep, clock changes and competing scheduler processes must not
  duplicate a check. Missed recurring opportunities coalesce instead of replaying
  a burst. One-shots outside their catch-up window are visibly missed.
- Claims and retries distinguish queued, started and completed work. A started
  but interrupted turn is recorded rather than blindly rerun. Injection failures
  and provider failures use bounded retries and backoff; persistent errors are
  visible and can pause work. Scheduler status exposes stalled or unavailable
  execution and its reason.
- Watchers honor read restrictions and command allowlists, use bounded payloads
  and timeouts, and treat source data as untrusted. File access is checked at
  creation and use, including rotation. Commands use argv without a shell and a
  sanitized environment. Web access blocks cloud metadata and blocks private
  addresses unless explicitly permitted, checking redirects and connect targets.
  Untrusted payloads cannot grant consent or create unbounded recurring work.
- Notes, summaries, payloads and accounting stay in the owning profile's local
  state. They may contain plaintext; receipts and guidance disclose that model
  turns are billed and configured probes access their sources. Cadence adds no
  telemetry.

## Visibility and owner control

Responsibility and own-time turns open with a compact desk view, also available
to the owner. It shows:

- Each responsibility's title, charter context, latest work, next opportunity,
  daily checks against its minimum and maximum, and any hold or missed minimum.
- Other active wakes and watchers and their next due opportunity.
- Execution and notification holds, responsibility capacity, the owner's last
  message, unanswered messages, and available usage and cost totals.

The owner can inspect, stop or remove work and see why it is waiting. Agent
receipts, commands, bundled guidance and tool descriptions describe the same
responsibility and trigger model and the same limits. Exact command spelling
and numeric bucket defaults are not prescribed here.

All active scheduled work, its charters, notes, ownership, limits and pending
occurrences must be accounted for when this model is installed. Supported work
is available without duplicate checks. Anything that cannot be represented is
visible to its owner with an explanation instead of being silently lost. Saved
recurring timing is expressed through triggers; it does not add a mandatory
interval constraint to a responsibility's daily limits and adaptive backstop.

## Acceptance cases

- Create, inspect, edit and delete a responsibility without supplying a recurring
  trigger. As soon as it is active, the automatic minimum backstop applies.
  Its charter and notes survive compaction,
  a new session in the same conversation and a restart. Owner removal or agent
  completion ends it visibly.
- For daily work intended at 9 a.m., set a minimum of one check per 24 hours
  and an explicit trigger for 9 a.m. in the owner's timezone. If the agent forgets
  to arrange the next check and the minimum would otherwise go unmet, the backstop
  prompts a check that reviews the work and fixes the next scheduled time.
  A fallback check counts toward the daily limits but does not replace the
  intended schedule for future checks.
- Support both owner-requested and agent-created responsibilities, prioritize
  the former, and require approval before running a proposed responsibility.
- Set a minimum and a permitted maximum of 30 checks per day at creation. Reject
  a minimum above the maximum and agent attempts to widen owner limits. Honor an
  optional initial check time and arrange an initial opportunity when omitted.
- With too few triggered starts, calculate the next automatic check from the
  time left in the day and remaining minimum wakeups. Recalculate as checks start;
  pending work does not satisfy the minimum. The maximum blocks further starts
  until the next daily period.
- Make a missed minimum and its cause visible when tokens, consent, cost,
  availability or busy state prevent it. Do not bypass a constraint to catch up.
- Schedule the next check by time or activate it from process, web or WebSocket
  events. Require an explicit time or condition for every trigger; reject
  creation or editing that supplies neither, even when the responsibility has
  an automatic minimum backstop. Each started check counts toward both daily limits.
- Support every trigger type in the trigger table, including recurring and
  agent-paced timing, file and command watchers, owner silence, gateway startup
  and all listed Hermes events, as well as WebSocket conditions. Require an
  explicit next time or delay for `self`; selecting a named event supplies an
  explicit condition without an extra timestamp.
- Fire owner-silence triggers at most once per human-silence episode and startup
  triggers only for new gateway processes. Apply configured filters and API-error
  aggregation. A watcher's deadline can produce one truthful "nothing happened"
  fallback without ending the watcher; a probe error must not produce a match.
- Every agent-initiated turn, including a silent check, own-time turn, watcher
  turn or continuation, consumes a global execution token on start. A pending
  injection consumes none. A responsibility check additionally consumes one
  responsibility token, with both tokens admitted together.
- Exhaust either execution bucket: eligible triggered work stays pending and
  consumes neither token nor daily check allowance. When capacity returns, start
  only if both tokens and all other guardrails permit it.
- Exhaust one responsibility's bucket while another has tokens: the second can
  still start within global capacity. Configure a large initial burst within
  owner limits; subsequent refill never exceeds capacity.
- Exhaust notification capacity or reach the unanswered hold while execution
  capacity is available: responsibility checks still run silently, record useful
  progress and retain findings. No notification token is spent just for running.
- Record check outcomes and notes, suppress silent final replies, and avoid
  duplicate notifications. Quiet checks alone neither end a responsibility nor
  impose another interval or automatic pause.
- Show the same compact desk information to the agent and owner, including next
  opportunities, daily counts, holds, missed minimums and available costs.
- Create supporting work within child and active-item limits. Deterministic
  watchers make no model call for unchanged sources. Own time is off by default
  and, when enabled, permits useful silent work within execution and cost limits.
- Arm and cancel independent short continuations only from a verified owner turn
  or its continuation. Enforce the delay bounds, preserve timers through restart,
  orphan them on a new session, consume a due timer if the chat is busy, and
  include intervening messages when a continuation runs.
- Refuse missing consent, prohibited platforms, cross-conversation IDs and
  attempts to choose a scheduling destination. Respect emergency stop and allow
  at most one scheduled turn in flight in a conversation.
- Restart or run competing schedulers without duplicate starts or spending tokens
  on unstarted work. Coalesce missed recurring opportunities, expose missed
  one-shots and interrupted turns, and apply bounded error backoff.
- Keep active work, notes, limits, ownership and pending occurrences accounted
  for on installation, without silent loss or duplicate checks. Show any item
  that cannot be represented and its reason to the owner.
