# Roles and scheduling

## Purpose

Cadence gives an agent time in its own conversation to work on standing
responsibilities and to react to time or events. The monolithic `pulse` tool is
retired. Managing roles is separate from scheduling other wakes and watchers;
a short-term continuation is separate from both. These are behavioral
boundaries, not final tool names or schemas.

This contract supersedes the role and agent-tool portions of
[v0.3 agency](v0.3-AGENCY.md) and the `pulse` interface in older specs where
they conflict. Those documents describe earlier designs; this spec does not
claim that the new interface is implemented.

## Roles

A role is a standing responsibility in the conversation, with a title, charter
and persistent working notes. It survives a new session in that conversation and
lasts until the owner removes it or the agent finishes it. Role management can
add, inspect, change and delete roles; the owner can stop a role, and the agent
can finish it. Managing a role does not require creating a scheduled wake or
specifying a recurring trigger.

A role has an approximate checks-per-day budget, chosen within the owner's
limits. The supported range includes at least 30 checks per day when the owner
permits it. This is a budget for full model turns, not a promise that exactly
that many checks occur, nor an evenly spaced schedule. The agent may use fewer.
The owner can change the budget; the agent may lower it but cannot widen the
owner's limit. The role rests when its execution budget is spent and becomes
eligible again in the next budget period.

An initial check time may be supplied when adding a role. Without one, Cadence
arranges an initial opportunity without requiring a separate schedule. After a
check, the agent decides when it is useful to check again, within the budget.
A due time is an opportunity, not a delivery guarantee: a busy conversation,
unavailability, consent or the owner's cost limit can delay or prevent a turn.
The agent can do useful work silently and keep its notes for the next check.

## Checks and notifications

A check is a model turn that spends role execution budget. A notification is a
message delivered to the owner. They are not the same: a check can make silent
progress or find nothing to report, and does not spend a notification token just
for running. The agent notifies only when useful. A notification hold does not
stop a role check; the agent retains anything worth reporting in its notes.

The existing per-chat interruption token bucket regulates notifications, not
role execution. Keep the owner's cost limit distinct from both: it limits
spend on agent-initiated work. Neither a full bucket nor a notification hold
changes a role's execution budget.

## Simplify the controls

For role checks, the budget and the agent's chosen next check replace the
stack of recurring-trigger interval floors, pacing bounds, wake spacing and
automatic no-change slowdown or pause. Do not require the owner or agent to
configure an interval alongside a budget. Repeated quiet checks do not by
themselves stop a standing role; the agent can decide to check less often.
This does not remove the notification bucket or the owner's cost limit, and
does not bypass consent, session isolation, one turn at a time in a busy chat,
or delivery and error handling. Limits specific to other wake or watcher
kinds are not silently removed by this role contract.

## Other time and events

Scheduling remains available for time-based wakes and reminders, deterministic
watchers, and the existing own-time behavior. Role management does not absorb
those capabilities. Their existing purpose, owner-requested reminder treatment,
consent and session boundaries remain intact when `pulse` is retired; the exact
replacement interface is not fixed here. Conversation-to-conversation
`request` remains separate and does not schedule another chat directly.

`follow_up` remains the separate short-term continuation facility. It gives
the agent another opportunity to act on the current conversation, including
intervening messages; it is not a role check or a notification. Its existing
eligibility, bounds, cancellation and lifecycle are not changed by this spec.

## Transition

Today `pulse` creates a role as an `every`, `cron` or `self` wake; the
configured role maximum defaults to 12. Role dispatches count against that
budget, while delivered notifications spend from the per-chat interruption
bucket. For recurring role work, an empty bucket holds messages rather than
the check. Other wake kinds can instead be held or dropped by that bucket.
Interval floors, per-chat wake spacing and the idle governor currently also
influence when a role runs. The new contract changes those role-specific
controls, not the present behavior of every wake kind.

Retiring `pulse` must not silently discard active roles, their charters, notes,
budgets or ownership, or existing reminders, wakes and watchers. Carry them
forward with their intended behavior, or make any item that cannot be carried
forward visible to its owner rather than silently losing or duplicating it.
Existing roles using fixed rhythms need an explicit transition to agent-chosen
checks under their budgets; a saved rhythm must not become an additional
mandatory interval constraint on the new role model. Preserve pending work and
avoid duplicate checks during the cutover. Update agent guidance, commands and
consumers with the new interface in the same rollout.

The open rename issue #10 describes renaming the monolithic tool to `cadence`.
This design replaces that tool rather than merely renaming it; it does not
settle replacement names, slash-command naming or a compatibility alias.

## Acceptance cases

- Add, inspect, edit and delete a role without supplying a recurring trigger;
  its charter and notes remain available across a new session.
- Set a permitted budget of 30 checks per day and optionally an initial check;
  without an initial time the role still gets an initial opportunity. The agent
  chooses later check times; fewer than 30 checks is valid, and the spent
  budget prevents further role checks until the next period.
- A silent check spends execution budget but no notification token. With an
  empty notification bucket, a role can still check silently; a useful message
  is held and the finding remains available for later reporting.
- Repeated `no_change` checks alone do not automatically pause a role or impose
  another interval; the agent can choose a later check itself.
- A due role check respects consent, conversation busy state and the owner's
  cost limit. A role budget does not authorize a notification or bypass them.
- Existing roles and other active scheduled work remain visible and are not
  silently lost or duplicated at transition. Existing reminders and watchers
  retain their behavior; `follow_up` remains independent.
