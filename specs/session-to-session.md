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
> *Master runs a turn; setup speech may happen. It arms its own 15-minute reminder and accepts.*
>
> **Kitchen:** "Master will remind you in 15 minutes."
>
> *15 minutes later, in Master, with no wake word:* "Time to take out the trash."

Master owns the reminder: it is an ordinary wake in Master's own chat, so
Master can be asked about it, snooze it, or cancel it. Kitchen owns nothing
after the agreement except a record that it asked.

Cadence carries the request and the answer; the asked chat does the work with
its own tools.

Implementation status: the immediate slice provides names/rename/ask/answer/list
and `/pulse name`. General content and normal recipient tools are supported;
ordinary setup speech is allowed, not silently buffered. Chosen names are explicit
self-opt-in; directory titles are not destination names. Operator owner/actor
maps are not required. Host injection consent, same-profile routing and internal
event provenance remain required. The first slice accepts notify:false, has no
tell/broadcast/nested ask or linked-wake failure reporting, and does not yet
treat a request turn as the owner's own turn for `pulse`. See [implementation boundaries](../docs/immediate-requests.md).

| Asked | Where | What the asked chat does in its request turn |
|---|---|---|
| "Remind me in Master to take out the trash in 15 minutes." | Kitchen asks Master | Arms its own reminder. Answers `accepted`; setup speech may happen. |
| "Tell Master dinner is ready." | Kitchen asks Master | Says it at once. Answers `accepted`. |
| "Play some jazz in Master." | Kitchen asks Master | Starts the music with its own music tool, or answers `declined` if it has none. |
| "Tell me on Telegram when the build is done." | A coding chat asks the Telegram DM | Sends the message when asked. Answers `accepted`. |
| "Have the Kitchen announce that I'm on my way home." | The Telegram DM asks Kitchen | Says it at once. Answers `accepted`. |
| "Stop the kitchen timer." | Master asks Kitchen | Cancels its own ringing countdown. Answers `accepted`. |
| *Kitchen's timer has been ringing for two minutes.* | Kitchen tells Master and Den | Each says the kitchen timer is going off. No answer. |

## Which conversations can be asked

Any conversation Cadence serves can ask, and be asked by, any other that is:

- a conversation this host can route;
- in the same Hermes profile;
- explicitly self-named for communication;
- on a platform the owner has not excluded.

Normal host route permissions and plugin injection consent apply. Communication
does not require a human-origin turn or an operator owner/actor map. Any host-routable session in this profile,
including groups, may self-name and participate.

## Names

The directory shows available host display titles and an optional chosen name.
An unnamed entry has `name:null,addressable:false`; it can be discovered but not
addressed. Titles, session IDs and route keys never resolve as address fallbacks.
Directory inspection is allowed before naming and never auto-enrolls a session.

A conversation enrolls itself with `request rename` or `/pulse name <name>`.
Only its own name changes. Names are 1-40 characters, case-insensitively unique
within this profile. Both source and destination must choose names to communicate.

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
| `names` | Any chat | None. Returns the directory: each conversation's title, chosen name (or null), whether it is addressable, its platform, and whether it can be reached now. |
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
{"action":"create","title":"Trash","note":"Remind them to take out the trash. Asked for from Kitchen.","trigger":{"kind":"at","after":"15m"}}
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

`notify:false` requests final-reply suppression where supported. Interim output
and ordinary setup speech may happen; it is not a silence guarantee. The immediate
slice accepts only false. A wake armed during an accepted request is linked to the request.

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

| Situation on `tell` | Result |
|---|---|
| `to` names a conversation that can be asked | One turn is started there. The result is `told`. |
| Unknown name, platform not allowed | Refused, as for `ask`. |
| The chat cannot be reached now | Refused: `unreachable`. The sender keeps the news or tells another chat. |

## Using `pulse` in a request turn

A request turn is an ordinary turn in the asked chat. In it the asked chat uses
`pulse` exactly as it would if the owner had spoken there: `create`, `list`,
`update`, `pause`, `resume`, and `cancel`. What it arms fires when it is due, and
it can change or cancel any wake in its own chat, so "cancel the trash reminder
in Master" works from the Kitchen. This holds whether the `ask` came from a
turn where the owner spoke or from a wake. It ends by calling `request` with
`answer`.

A request turn can arm up to `max_children_per_wake_turn` wakes. Starting a
role and `babysit` still need the owner in that chat.

## The answer turn

The answer is injected into the asking chat and runs as a turn there. The
asking agent tells the owner what was agreed, in its own words, or acts on a
refusal.

| Answer | What the asking agent does |
|---|---|
| `accepted` | Confirms to the owner, quoting the summary. |
| `declined` | Does the work itself, or tells the owner it cannot be done there. |
| `counter` | Accepts by asking again with the proposed terms, or does the work itself. |
| No answer in 60 seconds | Cadence records `unknown` and attempts one answer turn explaining that the target may have acted. The asking agent must check the target before retrying or doing the work itself. |

Requests are immediate transport, never scheduled cross-session wakes. Cadence
commits a durable random request ID and target identity before injection and
claims each request/answer delivery before handing it to Hermes. Duplicate
request envelopes do not run another target turn; duplicate answers do not run
another source turn. Rename does not change the identities in these records.
A host queue receipt proves only acceptance by the host, not execution or
successful delivery. A crash, disconnection, or lost answer after possible
acceptance is an unknown outcome, **not a decline**. Cadence never automatically
resubmits an ambiguously accepted request or answer. Records preserve the target's
known outcome separately from uncertain return delivery. Arbitrary external
side effects are not exactly once; a target can act and crash before answering.

A request ends when it is accepted, declined, countered, or becomes unknown. A counter may be
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

- **The chat's title**, for the directory. A title is never a name.
- **Whether a chat can be reached now.**
- **`inject_message` with another session's key.** Hermes already provides this.
- **Host-bound internal-event provenance**, to match durable requests and answers.
  Ordinary output must not be globally held or buffered.

## Invariants to test

- With `request_platforms: []`, every `ask` is refused and no turn runs in
  another chat.
- A request works between any two of the owner's DM chats on different
  platforms.
- A scheduled wake, watcher, or stream fires only in the chat that armed it.
- One `tell` starts exactly one turn in each chat it names and none back.
- A `tell` to several chats reaches the reachable ones when another is unreachable.
- Tells sent within 15 seconds to the same chat arrive in one turn, in order.
- A chat on an unlisted platform, in another profile, is never asked.
- An unknown or unreachable `to` starts no turn.
- Two conversations never have the same name, whatever the case.
- A request made before a rename is still answered and recorded after it.
- One `ask` starts exactly one request turn and at most one answer turn.
- A request turn that does not answer records `unknown` after 60 seconds and
  attempts one uncertainty notice, never automatically retrying the work.
- `answer` outside a request turn, or with another request's `id`, is refused.
- A request turn cannot `ask`.
- A wake armed in a request turn fires when it is due, whether the `ask` came
  from a turn where the owner spoke or from a wake.
- A request turn can change or cancel a wake the owner created in the asked chat.
- A fourth `ask` on the same matter is refused.
- An undeliverable linked wake starts exactly one turn in the asking chat.
- A request turn with `notify: false` suppresses final output where supported;
  ordinary streaming remains immediate and setup speech may happen.
