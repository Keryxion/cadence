---
name: cadence-usage
description: Own standing responsibilities and arrange explicit time or event opportunities in this conversation, within the owner's budgets.
---

Use Cadence to keep moving work forward between messages. Owner-assigned and
agent-created responsibilities are welcome. The tools help you act within the
owner's limits; temporary execution holds retain eligible work.

## Own the work

Use `responsibility` to create a title, charter, persistent notes and checks:

```json
{"action":"create","title":"Release readiness","charter":"Own release readiness: review blockers, investigate failures and prepare next actions.","checks":{"min_per_24h":1,"budget_per_24h":30},"owner_asked":true}
```

Set `owner_asked` only for a verified request in the current owner turn. Otherwise
omit it: agent-created work is welcome too. A responsibility lasts until finished
or removed and survives new sessions in the same chat. Use `list`, `get`, `update`,
`pause`, `resume`, `finish` (with a reason), or `delete`. Update `notes` with the
full notebook to keep. Inspect before acting on unfamiliar IDs.

The minimum is a scheduling fallback. When it wakes you, review the work and
fix the next explicit schedule. The budget sets token capacity and continuous
refill: 30 starts full with 30 tokens and restores 1.25 per hour. You can make
concentrated progress, then wait for refill. Neither budget is a midnight quota.
You cannot widen the owner's bounds.

## Arrange the next opportunity

Use `trigger` with the returned responsibility ID:

```json
{"action":"create","responsibility_id":"r_example","when":{"kind":"every","every":"1d","at":"09:00"}}
```

Choose a useful time in the owner's timezone. An `at` accepts local HH:MM,
tomorrow HH:MM, an ISO timestamp, or a delay such as in 10 minutes. For agent-paced work, set an `at`
trigger for the next check after each run. Every trigger needs an explicit time
or event condition. Use a deterministic watcher when it can identify what matters
without a model call. All of these are available:

- `at`, `every`, `cron`, and `owner_silent` with an explicit silence duration.
- `file` (changes/appended pattern), `process` (exit), `url` (response
  change/pattern), or allowlisted read-only `command` (change/success/failure/JSON).
- `startup`, `kanban_completed`, `kanban_blocked`, `kanban_worker_exited`,
  `subagent_done`, `api_error`, `reaction`, and `message_edited`.

For file watchers, relative paths resolve against the profile home. Prefer an
absolute path when observing a project file.

Use `get`, `list`, `update`, `pause`, `resume`, or `delete` to manage triggers.
Replacing `when` supplies the complete new condition. A standalone reminder or
watcher instead requires a `title` and `note` without a responsibility ID:

```json
{"action":"create","title":"Build finished","note":"Review the result and explain any failure.","when":{"kind":"process","pid":12345}}
```

Kanban triggers only see tasks whose worker runs in this profile.

Several triggers may contribute to one responsibility check. Read every reason
and instruction in the wake. It is one check, not one check per trigger. A probe
error means the observation failed; a deadline saying nothing happened does not
mean the task succeeded.

## Respond on every wake turn

A wake runs with your conversation's model, tools and permissions. Research,
file changes, investigation and preparation can all be useful silent progress.
Keep findings in responsibility notes and use `respond` to record the result:

```json
{"outcome":"progress","notify":false,"summary":"Reviewed blockers and prepared the next actions."}
```

`outcome` is `progress`, `no_change`, `done`, `blocked`, or `needs_attention`.
`notify` is required. Finishing a responsibility needs a nonempty completion
summary. For a one-off subject already settled, use outcome="done", notify=false. Use the responsibility tool for notes and the trigger tool for timing.
Do not type silence markers.

notify=false → your final reply is not posted; the work still counts. Write no text alongside tool calls on a wake turn; some platforms show tool progress.

Notify when worth the owner's attention: lead with the result or question, never
guilt or pester. A message hold does not stop useful work. Keep the finding for
later; do not repeatedly retry notification. Quiet checks alone do not pause a
responsibility. Choose sensible next opportunities instead of looping.

A check is a normal model turn using the conversation's context size, billed like one.
`/cadence status` and inspection show priced cost, unpriced calls and available usage.

## Budgets, receipts and owner control

Every agent-initiated turn consumes a global execution token when it starts;
a responsibility check also consumes its own token. Pending work spends none.
When either bucket is empty, work waits and inspect shows the hold and next
eligible time when known. Notification tokens and unanswered holds are separate.
Consent, cost, emergency stop, source restrictions and one turn at a time still
apply. Do not write settings or invent relay wakes to bypass a limit.

Relay the actual receipt, including timing and holds. A proposed item is **not
armed**: ask the owner to use `/cadence approve <id>`. Report a refusal truthfully
with the corrective information; do not claim scheduling succeeded.

The owner can use `/cadence status`, `desk`, `list`, `why <id>`, `pause`, `resume`,
`delete`, `budget <id> <minimum> <budget>`, and `on`/`off`. `/cadence` is a control
panel, not an owner reply. Only the owner can enable a disabled conversation.

`follow_up` is a separate short continuation tool for owner work already
underway (15 seconds through 15 minutes). `request` communicates with explicitly
self-named conversations in this profile; names come from `request names`, and
each participant opts in with `request rename`. Titles and raw route IDs are not
address fallbacks. Scheduled work always fires in the chat that owns it; ask
another chat to accept and arrange its own work instead of choosing a destination.
