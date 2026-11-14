# Session to session: one conversation asks another

Part of being proactive is being able to talk to the owner's other
conversations. This spec lets any conversation ask another to do something. It
works the same for every Hermes conversation Cadence serves: a messaging DM, a
voice device, a coding chat.

A wake still fires only in the chat that armed it. What crosses between chats
is a request and its answer. The request runs a turn in the other chat, the
answer runs a turn back in the first, and both record what was agreed: who is
doing what.

> **In the Kitchen:** "Remind me in Master to take out the trash in 15 minutes."
> **Kitchen:** "I'll ask Master."
>
> *Master runs a turn, silently. It arms its own 15-minute reminder and accepts.*
>
> **Kitchen:** "Master will remind you in 15 minutes."
>
> *15 minutes later, in Master, with no wake word:* "Time to take out the trash."

Master owns the reminder: it is an ordinary wake in Master's own chat, so
Master can be asked about it, snooze it, or cancel it. Kitchen owns nothing
after the agreement except a record that it asked.

Cadence carries the request and the answer; the asked chat does the work with
its own tools.

| Asked | Where | What the asked chat does in its request turn |
|---|---|---|
| "Remind me in Master to take out the trash in 15 minutes." | Kitchen asks Master | Arms its own reminder. Answers `accepted`, silently. |
| "Tell Master dinner is ready." | Kitchen asks Master | Says it at once. Answers `accepted`. |
| "Play some jazz in Master." | Kitchen asks Master | Starts the music with its own music tool, or answers `declined` if it has none. |
| "Tell me on Telegram when the build is done." | A coding chat asks the Telegram DM | Sends the message when asked. Answers `accepted`. |
| "Have the Kitchen announce that I'm on my way home." | The Telegram DM asks Kitchen | Says it at once. Answers `accepted`. |

## Which conversations can be asked

Any conversation Cadence serves can ask, and be asked by, any other that is:

- a DM chat, not a group;
- in the same Hermes profile;
- on a platform the owner has not excluded.

| Setting | Default | Meaning |
|---|---|---|
| `request_platforms` | every platform Cadence serves | Platforms whose chats may be asked. A list narrows it; `[]` turns requests off. |

Requests never leave the owner's own conversations: a chat in another profile,
or a group, is never asked.

## Asking

Asking is its own tool, `request`. `pulse` is unchanged: it schedules a chat's
own wakes and has no destination.

| `request` action | Used by | Fields |
|---|---|---|
| `ask` | The chat that wants something | `to` (a `send_message` target, `platform:name`), `note` (what is wanted, in words) |
| `answer` | The chat that was asked, during the request turn | `id`, `outcome` (`accepted`, `declined`, `counter`), `summary`, `notify` |
| `list` | Either chat | None. Returns the requests this chat asked or was asked, with their outcomes. |

Kitchen calls `request`:

```json
{"action":"ask","to":"converse:Master","note":"Remind them to take out the trash in 15 minutes."}
```

```json
{"ok":true,"request":"r_7","to":"Master","receipt":"Asked Master. Nothing is set until Master answers."}
```

`to` is resolved through the Hermes channel directory, with the names and
aliases `send_message` accepts.

| Situation | Result |
|---|---|
| Resolves to one chat on a listed platform | The request is recorded and a turn is started in that chat. |
| Platform not in `request_platforms` | Refused: `not_allowed`. |
| No such chat, or it has never had a conversation | Refused: `unknown`. |
| More than one chat matches | Refused: `ambiguous`, listing the matches so the agent can ask the owner. |
| The chat cannot be reached now | Refused: `unreachable`. The asking agent does the work itself or tells the owner. |

## The request turn

Cadence injects the request into the asked chat. It runs as a turn there, on
that chat's model. The text names the asking chat, quotes the note, and says the
owner is not in this room and has not seen the request.

The asked agent decides. To accept, it does what is needed in its own chat,
such as arming its own wake with `pulse`:

```json
{"action":"create","title":"Trash","note":"Remind them to take out the trash. Asked for from Kitchen.","trigger":{"kind":"at","after":"15m"},"owner_asked":true}
```

Then it answers with `request`:

```json
{"action":"answer","id":"r_7","outcome":"accepted","summary":"I'll remind here in 15 minutes.","notify":false}
```

| `outcome` | Meaning |
|---|---|
| `accepted` | The asked chat has taken the work. `summary` says what it will do. |
| `declined` | It will not. `summary` says why. Nothing was armed. |
| `counter` | It proposes something else in `summary`, such as a different time. Nothing was armed. |

`notify` says whether the asked chat speaks or sends a message in this turn.
It is `false` for arranging something later and `true` for "tell Master dinner
is ready". A wake armed during an accepted request is linked to the request.

## Using `pulse` in a request turn

A request turn is neither a human turn nor a wake turn. In it the asked chat
uses `pulse` for its own chat exactly as it would for its owner: `create`,
`list`, `update`, `pause`, `resume`, and `cancel`. It ends by calling `request`
with `answer`.

The asker's standing comes with the request:

| The `ask` was made | In the request turn |
|---|---|
| In a turn where the owner had just spoken | The request carries the owner's standing. `owner_asked: true` on a one-time wake is honoured, so the reminder is not muted, capped, or held by wake spacing. Wakes the owner created in the asked chat can be changed or cancelled, so "cancel the trash reminder in Master" works from the Kitchen. |
| From a wake turn | No owner standing. Anything armed is the agent's own follow-up, with the usual limits, and the owner's wakes cannot be changed. |

A request turn can arm up to `max_children_per_wake_turn` wakes. Starting a
role and `babysit` still need the owner in that chat. The request text tells the
asked agent which standing it has.

## The answer turn

The answer is injected into the asking chat and runs as a turn there. The
asking agent tells the owner what was agreed, in its own words, or acts on a
refusal.

| Answer | What the asking agent does |
|---|---|
| `accepted` | Confirms to the owner, quoting the summary. |
| `declined` | Does the work itself, or tells the owner it cannot be done there. |
| `counter` | Accepts by asking again with the proposed terms, or does the work itself. |
| No answer in 60 seconds | Cadence reports `no_answer`. The agent treats it as `declined`. |

A request ends when it is accepted, declined, or unanswered. A counter may be
followed by one more `ask`; after three asks on the same matter Cadence refuses
further ones and the asking agent decides alone.

## Who is doing what

Each request is recorded with both chats, the note, the outcome, the summary,
and any wake armed for it. Both chats see it:

- In the asking chat, `request list` shows "asked Master: trash reminder,
  accepted".
- In the asked chat, `request list` shows the same request, and `pulse list`
  marks the wake "asked for from Kitchen".

The asked chat alone can change or cancel its wake. The asking chat changes it
by asking again.

When a linked wake cannot be delivered, for example Master is not connected at
the deadline, Cadence starts a turn in the asking chat saying so. The work
falls back to the chat that asked.

## Limits

| Limit | Applies to |
|---|---|
| Turns per day and cost | Each turn is charged to the chat it runs in. |
| Requests in flight | One per pair of chats; a second waits for the first to end. |
| Depth | A request turn cannot `ask` a third chat. |
| Quiet hours | A request the owner just made is not held. A request made from a wake turn is held by the asked chat's quiet hours. |
| Busy chat | The request waits for the asked chat's current exchange, within the 60 seconds. |

Request and answer turns are not wakes: they do not count toward `max_active`
or the no-op governor.

## What Cadence needs from outside

- **Channel directory entries for every chat.** A voice device must be listed
  by its device name, so `converse:Master` resolves.
- **Whether a chat can be reached now.**
- **`inject_message` with another session's key.** Hermes already provides this.
- **Silent turns on every platform.** A request turn answered with
  `notify: false` must send and speak nothing.

## Invariants to test

- With `request_platforms: []`, every `ask` is refused and no turn runs in
  another chat.
- A request works between any two of the owner's DM chats on different
  platforms.
- A wake never fires outside the chat that armed it.
- A chat on an unlisted platform, in another profile, or in a group is never
  asked.
- An ambiguous, unknown, or unreachable `to` starts no turn.
- One `ask` starts exactly one request turn and at most one answer turn.
- A request turn that does not answer produces `no_answer` in the asking chat
  once, after 60 seconds.
- `answer` outside a request turn, or with another request's `id`, is refused.
- A request turn cannot `ask`.
- `owner_asked` in a request turn is honoured only when the `ask` came from a
  turn where the owner had just spoken.
- A request without owner standing cannot change a wake the owner created.
- A fourth `ask` on the same matter is refused.
- An undeliverable linked wake starts exactly one turn in the asking chat.
- A request turn with `notify: false` sends and speaks nothing.
