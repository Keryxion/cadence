# Responsibilities and scheduling

## Purpose

Cadence gives an agent time in its own conversation to work on standing
responsibilities and to react to time or events. The monolithic `pulse` tool is
retired. The `responsibility` tool assigns and manages standing responsibilities and their general
charters. The separate `trigger` tool schedules a responsibility's next run by
time or activates it based on an event. A short-term continuation is separate
from both. Tool
schemas and detailed trigger semantics remain to be specified.

This contract supersedes the role and agent-tool portions of
[v0.3 agency](v0.3-AGENCY.md) and the `pulse` interface in older specs where
they conflict. Those documents describe earlier designs; this spec does not
claim that the new interface is implemented.

## Responsibilities

A responsibility is a standing responsibility in the conversation, with a title, general
charter and persistent working notes. It survives a new session in that
conversation and lasts until the owner removes it or the agent finishes it.
The `responsibility` tool can assign, inspect, change and delete responsibilities; the owner can
stop a responsibility, and the agent can finish it. Responsibilities may be requested by the owner
or created proactively by the agent; both are welcome. Owner-requested responsibilities
have higher priority than agent-created responsibilities. How that priority affects
scheduling, contention and resource allocation remains open; it does not
eliminate agent-created responsibilities. Managing a responsibility does not require creating a
trigger or specifying a recurring schedule.

Each responsibility has a minimum and a maximum number of checks per day, set
at creation within the owner's limits; the minimum cannot exceed the maximum.
The supported maximum includes at least
30 checks per day when the owner permits it. These counts apply to full model
turns, not notifications. The minimum provides an adaptive heartbeat and backstop:
if triggers have not produced enough runs, Cadence calculates the next automatic
check from the time remaining in the day and the remaining minimum wakeups, so
the responsibility is not neglected. This is not a fixed heartbeat or a delivery
guarantee: the global execution bucket, the responsibility's own bucket, busy or
offline conversations, consent, or the owner's cost limit can prevent the minimum
from being met. A missed minimum is visible to the owner.
The maximum is an execution limit: once spent,
the responsibility rests until the next daily period. The owner can change the
minimum and maximum; the agent cannot widen the owner's limits.

An initial check time may be supplied when adding a responsibility. Without one, Cadence
arranges an initial opportunity without requiring a separate schedule. After a
check, the agent can use `trigger` to schedule a useful next opportunity by time
or activate one based on an event. Cadence's adaptive minimum backstop operates
alongside triggers, within the maximum.
A due time is an opportunity, not a delivery guarantee: a busy conversation,
unavailability, consent, the execution bucket or the owner's cost limit can delay
or prevent a turn.
The agent can do useful work silently and keep its notes for the next check.

## Checks and notifications

A check is a model turn that counts toward the responsibility's daily minimum and
maximum. A notification is a
message delivered to the owner. They are not the same: a check can make silent
progress or find nothing to report, and does not spend a notification token just
for running. The agent notifies only when useful. A notification hold does not
stop a responsibility check; the agent retains anything worth reporting in its notes.

The global agent-turn start token bucket limits execution independently of the
overall user-interruption notification bucket. Every agent-initiated turn,
including a silent responsibility check, consumes an execution token when it
starts. If no execution token is available, triggered work is delayed until one
is available, not discarded; it remains subject to the other applicable limits
and guardrails when it can run. The notification bucket governs interruptions
independently: a turn does not consume a notification token merely by starting.
Keep the owner's cost limit distinct from both buckets: it limits spend on
agent-initiated work. Neither bucket changes a responsibility's daily check limits.

Each responsibility also has its own token bucket, separate from both global
buckets. A responsibility check consumes a token from its responsibility bucket
as well as the global execution bucket when it starts. If its responsibility
bucket is empty, eligible work is deferred until a token is available, not
discarded, subject to the other applicable limits and guardrails. A pending check
does not count toward the daily minimum or maximum; the adaptive backstop accounts
for checks that have started. The responsibility bucket does not replace or change
the daily minimum or maximum. Bucket capacity and refill details are not specified
here.

## Simplify the controls

For responsibility checks, the daily minimum and maximum and triggers replace the
stack of recurring-trigger interval floors, pacing bounds, wake spacing and
automatic no-change slowdown or pause. Do not require the owner or agent to
configure an interval alongside the daily limits. Repeated quiet checks do not by
themselves stop a standing responsibility; the agent can decide to check less often.
This does not remove the execution, responsibility or notification buckets or the owner's cost limit, and
does not bypass consent, session isolation, one turn at a time in a busy chat,
or delivery and error handling. Limits specific to other wake or watcher
kinds are not silently removed by this responsibility contract.

## Triggers, other time and events

The separate `trigger` tool schedules the next run for a responsibility by time
or activates it based on an event. Event sources include processes,
the web and WebSocket connections. This supports proactive response to events,
not just periodic polling. Triggered runs count toward both the daily minimum and
maximum and are subject to both execution and responsibility buckets and the same
consent, cost and conversation boundaries. An unavailable execution or
responsibility token delays triggered work rather than discarding it; a delayed
run counts when it starts, not when triggered.
The minimum does not bypass those boundaries. A scheduled or activated run is
an opportunity, not a delivery guarantee. The details of
sources and WebSocket behavior are not specified here.

Scheduling remains available for time-based wakes and reminders, deterministic
watchers, and the existing own-time behavior. Responsibility management does not absorb
those capabilities. Their existing purpose, owner-requested reminder treatment,
consent and session boundaries remain intact when `pulse` is retired; the exact
replacement interface for other work is not fixed here. Conversation-to-conversation
`request` remains separate and does not schedule another chat directly.

`follow_up` remains the separate short-term continuation facility. It gives
the agent another opportunity to act on the current conversation, including
intervening messages; it is not a responsibility check or a notification. Its
turns are subject to the global execution bucket; its existing eligibility,
bounds, cancellation and lifecycle are otherwise unchanged by this spec.

## Transition

Today `pulse` creates a role as an `every`, `cron` or `self` wake; the
configured role maximum defaults to 12. Role dispatches count against that
budget, while delivered notifications spend from the per-chat interruption
bucket. For recurring role work, an empty bucket holds messages rather than
the check. Other wake kinds can instead be held or dropped by that bucket.
Interval floors, per-chat wake spacing and the idle governor currently also
influence when a responsibility runs. The new contract changes those responsibility-specific
controls, not the present behavior of every wake kind.

Retiring `pulse` must not silently discard active roles, their charters, notes,
budgets or ownership, or existing reminders, wakes and watchers. Carry them
forward with their intended behavior, or make any item that cannot be carried
forward visible to its owner rather than silently losing or duplicating it.
Existing roles using fixed rhythms need an explicit transition to triggers and
the adaptive backstop under their daily minimum and maximum; a saved rhythm must not become an additional
mandatory interval constraint on the new responsibility model. Preserve pending work and
avoid duplicate checks during the cutover. Update agent guidance, commands and
consumers with the new interface in the same rollout.

The open rename issue #10 describes renaming the monolithic tool to `cadence`.
This design replaces that tool rather than merely renaming it; it names
`responsibility` and `trigger` but does not settle slash-command naming or a
compatibility alias.

## Acceptance cases

- Add, inspect, edit and delete a responsibility without supplying a recurring trigger;
  its charter and notes remain available across a new session.
- Set a minimum and a permitted maximum of 30 checks per day at creation; reject
  a minimum above the maximum. Optionally set an initial check; without an
  initial time the responsibility still gets an initial opportunity. The maximum
  prevents further checks until the next daily period.
- With too few triggered runs, Cadence calculates the next automatic check using
  the time left in the day and remaining minimum wakeups. As triggered checks
  occur, they count toward both limits and the backstop adapts to the remaining
  minimum; it is not a fixed-interval heartbeat.
- If either execution or responsibility bucket, busy, offline, consent or cost constraints prevent the minimum from being
  met, the missed minimum is visible to the owner; no constraint is bypassed.
- Owner-requested and agent-created responsibilities are both supported; the
  former have higher priority, without prescribing a contention policy.
- Schedule the next run with `trigger` by time or activate it from an event source, including
  processes, the web or WebSocket connections, so the agent can respond
  proactively within the responsibility's daily maximum and safety boundaries.
- Every agent-initiated turn, including a silent check, consumes a global execution
  token on start. A silent responsibility check counts toward its daily limits but
  spends no notification token. With an empty notification bucket and an available
  execution token, a responsibility can still check silently; a useful message is
  held and the finding remains available for later reporting.
- With no execution token, triggered work remains pending rather than being
  discarded and is delayed until a token is available; it starts only if the
  applicable daily maximum, consent, busy state and cost limits also allow it.
  The delayed check counts when started, and the adaptive backstop accounts for
  started checks rather than treating a pending trigger as a check.
- With an empty responsibility bucket, eligible work for that responsibility is
  deferred until a token is available, not discarded. A started check consumes
  both its responsibility token and a global execution token; its daily limits
  and the adaptive backstop count starts, not pending work. The independent
  notification bucket and consent, busy state and cost guardrails still apply.
- Repeated `no_change` checks alone do not automatically pause a responsibility or impose
  another interval; the agent can choose a later check itself.
- A due responsibility check respects consent, conversation busy state and the owner's
  cost limit. Daily check limits do not authorize a notification or bypass them.
- Existing roles and other active scheduled work remain visible and are not
  silently lost or duplicated at transition. Existing reminders and watchers
  retain their purpose and guardrails, subject to the global execution bucket;
  `follow_up` remains separate and is also subject to that bucket.
