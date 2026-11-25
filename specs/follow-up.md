# Short continuations

## Why

Work underway may need another turn shortly after a tool returns or something
changes. `follow_up` provides that opportunity with current conversation history,
including intervening messages, without creating a standing responsibility.

## Tool contract

Accept exactly one of these JSON shapes; reject extra fields:

```json
{"at":"30s"}
```

```json
{"cancel":"timer_id"}
```

`at` is a relative delay from 15 seconds through 15 minutes inclusive. Only a
verified owner turn or its continuation may arm a timer. Each call creates an
independent timer; replacing one requires explicitly cancelling its ID. Arming
returns `id`, `armed: true`, and `due_at` as an absolute UTC timestamp.

Cancellation is scoped to this conversation, safe to repeat, and returns the
resulting status or `already_started`. Another conversation's ID reveals nothing.
Timers retain originating chat, session and turn identity, survive gateway
restarts, and are orphaned by a new session so work cannot resume there.

At expiry the model receives scheduled/current timestamps and current history.
A continuation may arm another timer. If the chat already has a turn underway,
consume the due timer without queuing a continuation. Otherwise starting requires
a global execution token and applicable consent, availability and cost checks;
lack of capacity defers eligible work. Starting is not a responsibility check
and does not consume a responsibility token or count toward its minimum. Resuming
owner-requested work does not itself spend an interruption token.

## Acceptance

Enforce exact call shapes, delay bounds and owner-turn eligibility. Verify
independent timers, cancellation isolation/idempotence, restart persistence,
new-session orphaning, busy-chat consumption, execution admission and intervening
message context. Never count a queued timer as a started turn.
