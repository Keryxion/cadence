# Session to session: conversations ask and tell each other

Part of being proactive is being able to talk to the owner's other
conversations. This spec lets any conversation ask or tell another. It
works the same for every Hermes conversation Cadence serves: a messaging DM, a
voice device, a coding chat.

Turns go both ways. Any conversation can start a turn in another, and the
other can start one back, from an ordinary turn or from a wake:

- **Ask** when the other chat should decide or do something. The request runs
  a turn there, the answer runs a turn back, and both record what was agreed:
  who is doing what.
- **Tell** when the other chat only needs to know. It runs one turn there and
  nothing comes back.

A scheduled wake, watcher, or stream still belongs to one chat: the chat that
armed it owns it and it fires there. When it fires, that chat can ask or tell
any other.

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
| "Stop the kitchen timer." | Master asks Kitchen | Cancels its own ringing countdown. Answers `accepted`. |
| *Kitchen's timer has been ringing for two minutes.* | Kitchen tells Master and Den | Each says the kitchen timer is going off. No answer. |

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

## Names

Every conversation Cadence serves has a name, unique within the profile. A
request is addressed to a name.

- **Automatic.** A conversation gets a name the first time Cadence sees it,
  taken from the chat's own title in Hermes, such as `Telegram` or
  `Arya: Master`. If that is taken, a number is added.
- **Chosen.** A conversation can give itself a better name at any time, and the
  owner can name it with `/pulse name <name>`. A name is 1 to 40 characters,
  compared without regard to case, and refused if another conversation has it.

A platform can tell its conversations how to name themselves. The voice server's
instructions have each device name its conversation after the device, so the
Master bedroom's conversation is `Master`.

Renaming never breaks anything: requests and their records point at the
conversation, not at the name it had.

## Asking

Asking is its own tool, `request`. `pulse` is unchanged: it schedules a chat's
own wakes and has no destination.

| `request` action | Used by | Fields |
|---|---|---|
| `ask` | The chat that wants something | `to` (a conversation's name), `note` (what is wanted, in words) |
| `answer` | The chat that was asked, during the request turn | `id`, `outcome` (`accepted`, `declined`, `counter`), `summary`, `notify` |
| `tell` | Any chat | `to` (a conversation's name, or a list of names), `note` (what it should know), `urgent` (optional) |
| `list` | Either chat | None. Returns the requests this chat asked or was asked, with their outcomes. |
| `names` | Any chat | None. Returns the conversations that can be asked: name, platform, and whether each can be reached now. |
| `rename` | Any chat, for itself | `name`. |

Kitchen calls `request`:

```json
{"action":"ask","to":"Master","note":"Remind them to take out the trash in 15 minutes."}
```

```json
{"ok":true,"request":"r_7","to":"Master","receipt":"Asked Master. Nothing is set until Master answers."}
```

A conversation naming itself:

```json
{"action":"rename","name":"Master"}
```

| Situation on `ask` | Result |
|---|---|
| `to` names a conversation that can be asked | The request is recorded and a turn is started in that chat. |
| Its platform is not in `request_platforms` | Refused: `not_allowed`. |
| No conversation has that name | Refused: `unknown`, listing the names that exist so the agent can pick or ask the owner. |
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

## Telling

`tell` is one-way. Cadence starts a turn in the other chat with the note and
who sent it. The agent there decides what to do with it: say it, act on it, or
stay silent. There is no answer and no turn back.

A build watcher in a coding chat, reporting to the owner's messaging DM:

```json
{"action":"tell","to":"Telegram","note":"The build finished: 5 checks passed, 1 failed (unit tests)."}
```

`to` may be a list. One turn runs in each conversation named, and the result
reports each name separately, so one that cannot be reached does not hold up
the others:

```json
{"action":"tell","to":["Master","Den"],"note":"The kitchen timer has been ringing for two minutes."}
```

```json
{"ok":true,"results":{"Master":"told","Den":"unreachable"}}
```

A told chat has no owner standing from the sender: it cannot arm an owner
reminder or change the owner's wakes on the strength of a `tell`. To arrange
that, `ask`.

| Situation on `tell` | Result |
|---|---|
| `to` names a conversation that can be asked | One turn is started there. The result is `told`. |
| Unknown name, platform not allowed | Refused, as for `ask`. |
| The chat cannot be reached now | Refused: `unreachable`. The sender keeps the news or tells another chat. |

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
| Requests in flight | One `ask` per pair of chats; a second waits for the first to end. |
| Tells | At most one every 15 seconds from one chat to another. Notes sent sooner are delivered together in the next turn. |
| Depth | A request turn cannot `ask` a third chat. |
| Quiet hours | An `ask` or `tell` the owner just made is not held. One made from a wake turn is held by the other chat's quiet hours, unless it is `urgent` and the owner allows urgent wakes through. |
| Busy chat | The request waits for the asked chat's current exchange, within the 60 seconds. |

Request and answer turns are not wakes: they do not count toward `max_active`
or the no-op governor.

## What Cadence needs from outside

- **The chat's title**, for the automatic name.
- **Whether a chat can be reached now.**
- **`inject_message` with another session's key.** Hermes already provides this.
- **Silent turns on every platform.** A request turn answered with
  `notify: false` must send and speak nothing.

## Invariants to test

- With `request_platforms: []`, every `ask` is refused and no turn runs in
  another chat.
- A request works between any two of the owner's DM chats on different
  platforms.
- A scheduled wake, watcher, or stream fires only in the chat that armed it.
- One `tell` starts exactly one turn in each chat it names and none back.
- A `tell` to several chats reaches the reachable ones when another is unreachable.
- Tells sent within 15 seconds to the same chat arrive in one turn, in order.
- A `tell` gives the told chat no owner standing.
- A chat on an unlisted platform, in another profile, or in a group is never
  asked.
- An unknown or unreachable `to` starts no turn.
- Two conversations never have the same name, whatever the case.
- A request made before a rename is still answered and recorded after it.
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
