# Responsibilities and scheduling

## Purpose

Cadence gives an agent time in its own conversation to work on standing
responsibilities and to react to time or events. The monolithic `pulse` tool is
retired. The `responsibility` tool assigns and manages standing responsibilities and their general
charters. The separate `trigger` tool requests the next run for a responsibility, based
on time or an event. A short-term continuation is separate from both. Tool
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
turns, not notifications, and do not imply an evenly spaced schedule. The minimum
is a desired service level, not a guarantee: busy or offline conversations,
consent, or the owner's cost limit can prevent it from being met. A missed
minimum is visible to the owner. The maximum is an execution limit: once spent,
the responsibility rests until the next daily period. The owner can change the
minimum and maximum; the agent cannot widen the owner's limits.

An initial check time may be supplied when adding a responsibility. Without one, Cadence
arranges an initial opportunity without requiring a separate schedule. After a
check, the agent uses `trigger` to request a useful next opportunity by time or
an event, within the maximum and aiming for the minimum.
A due time is an opportunity, not a delivery guarantee: a busy conversation,
unavailability, consent or the owner's cost limit can delay or prevent a turn.
The agent can do useful work silently and keep its notes for the next check.

## Checks and notifications

A check is a model turn that counts toward the responsibility's daily minimum and
maximum. A notification is a
message delivered to the owner. They are not the same: a check can make silent
progress or find nothing to report, and does not spend a notification token just
for running. The agent notifies only when useful. A notification hold does not
stop a responsibility check; the agent retains anything worth reporting in its notes.

The existing per-chat interruption token bucket regulates notifications, not
responsibility execution. Keep the owner's cost limit distinct from both: it limits
spend on agent-initiated work. Neither a full bucket nor a notification hold
changes a responsibility's daily check limits.

## Simplify the controls

For responsibility checks, the daily minimum and maximum and the agent's chosen next check replace the
stack of recurring-trigger interval floors, pacing bounds, wake spacing and
automatic no-change slowdown or pause. Do not require the owner or agent to
configure an interval alongside the daily limits. Repeated quiet checks do not by
themselves stop a standing responsibility; the agent can decide to check less often.
This does not remove the notification bucket or the owner's cost limit, and
does not bypass consent, session isolation, one turn at a time in a busy chat,
or delivery and error handling. Limits specific to other wake or watcher
kinds are not silently removed by this responsibility contract.

## Triggers, other time and events

The separate `trigger` tool requests the next run for a responsibility. A
trigger can be based on time or diverse event sources, including processes,
the web and WebSocket connections. This supports proactive response to events,
not just periodic polling. Triggered runs are responsibility checks subject to
the same daily maximum, consent, cost and conversation boundaries. The minimum
does not bypass those boundaries. A trigger
is a request for an opportunity, not a delivery guarantee. The details of
sources and WebSocket behavior are not specified here.

Scheduling remains available for time-based wakes and reminders, deterministic
watchers, and the existing own-time behavior. Responsibility management does not absorb
those capabilities. Their existing purpose, owner-requested reminder treatment,
consent and session boundaries remain intact when `pulse` is retired; the exact
replacement interface for other work is not fixed here. Conversation-to-conversation
`request` remains separate and does not schedule another chat directly.

`follow_up` remains the separate short-term continuation facility. It gives
the agent another opportunity to act on the current conversation, including
intervening messages; it is not a responsibility check or a notification. Its existing
eligibility, bounds, cancellation and lifecycle are not changed by this spec.

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
Existing roles using fixed rhythms need an explicit transition to agent-chosen
checks under their daily minimum and maximum; a saved rhythm must not become an additional
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
  initial time the responsibility still
  gets an initial opportunity. The agent chooses later checks aiming for the
  minimum; the maximum prevents further checks until the next daily period.
- If busy, offline, consent or cost constraints prevent the minimum from being
  met, the missed minimum is visible to the owner; no constraint is bypassed.
- Owner-requested and agent-created responsibilities are both supported; the
  former have higher priority, without prescribing a contention policy.
- Request the next run with `trigger` for time or an event source, including
  processes, the web or WebSocket connections, so the agent can respond
  proactively within the responsibility's daily maximum and safety boundaries.
- A silent check counts toward the daily limits but spends no notification token. With an
  empty notification bucket, a responsibility can still check silently; a useful message
  is held and the finding remains available for later reporting.
- Repeated `no_change` checks alone do not automatically pause a responsibility or impose
  another interval; the agent can choose a later check itself.
- A due responsibility check respects consent, conversation busy state and the owner's
  cost limit. Daily check limits do not authorize a notification or bypass them.
- Existing roles and other active scheduled work remain visible and are not
  silently lost or duplicated at transition. Existing reminders and watchers
  retain their behavior; `follow_up` remains independent.
