# Check results and notification decisions

## Why

Useful work can be silent. A structured result lets Cadence distinguish progress,
completion and a need for attention without guessing from final reply text. It
also keeps the agent's decision to notify separate from permission to interrupt.

## `respond` tool

This tool answers only the check running in the current conversation. The host
binds it to the started occurrence and attempt; callers cannot choose a check,
responsibility or destination by ID. Ordinary owner turns and stale or foreign
attempts are refused without changing another check.

| Field | Type | Required | Meaning |
|---|---|---|---|
| `outcome` | `progress`, `no_change`, `done`, `blocked`, `needs_attention` | Yes | Useful work, nothing to do, completed work, a blockage, or need for owner attention |
| `notify` | Boolean | Yes | Whether the agent wants its final reply delivered |
| `summary` | String, at most 1,024 characters | No; defaults empty | Concise result recorded for inspection and the next check |

Reject extra fields. Notes are managed by the responsibility tool; next-check
timing is managed by the trigger tool. This tool does not combine either of
those operations with recording a result.

```json
{"outcome":"progress","notify":false,"summary":"Reviewed release blockers and prepared the next actions."}
```

Return `ok: true` and `status: awaiting_turn_end`. The last valid call in the
current attempt wins. Finalize successful results only when the turn finishes
without failure; a failed or interrupted turn is recorded as such. `done` ends
the work with its summary as the completion reason; a responsibility completion
requires a nonempty reason and cancels its attached pending work. Silence or
`no_change` does not end a responsibility.

`notify: false` suppresses the final reply through structured gateway handling.
The agent must not type silence markers or emit commentary alongside tool calls
that would expose a silent turn. `notify: true` permits delivery only within
notification capacity, consent and unanswered-message rules. Otherwise hold the
message and retain the finding; an eligible check still counts as work. Owner
interruption or cancellation can force silence even after a notification request.
Duplicate summaries must not cause repeated notifications.

Messages lead with the result or question and do not guilt or pester the owner.
Silent research, file changes and preparation count as progress. Neither silent
progress nor repeated quiet checks automatically pause a responsibility. Recording
a result does not spend execution tokens again: execution and daily counts were
charged when the check started.

## Acceptance

Verify field validation and attempt/conversation binding, last-valid-call
behavior, successful completion versus failure, explicit completion reasons,
final-reply suppression, forced silence, held notifications and deduplication.
A silent useful result remains visible as progress and does not consume a
notification token merely for having run.
