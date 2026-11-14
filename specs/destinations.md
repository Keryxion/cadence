# Destinations: reminders in another chat

A wake fires in the chat that armed it. This spec lets a wake name a different
chat to fire in, so a reminder asked for in one room is spoken in another.

> **In the Kitchen:** "Remind me in Master to take out the trash in 15 minutes."
> **Kitchen:** "I'll remind you in Master in 15 minutes."
>
> *15 minutes later, in Master, with no wake word:* "Time to take out the trash."
> **In Master:** "Give me ten more minutes."
> **Master:** "I'll remind you again in ten."

The reminder is an ordinary wake. It runs as a turn in Master's conversation,
so Master's agent says it in its own words and can take the reply.

## The owner's setting

Destination isolation stays the default for every platform the owner has not
listed.

| Setting | Default | Meaning |
|---|---|---|
| `destination_platforms` | `["converse"]` | Platforms whose chats may be named as a destination. `[]` turns destinations off. |

A destination must be a DM chat on a listed platform, in the same Hermes
profile as the arming chat. The arming chat may be any chat where `pulse`
works, so a reminder for Master can be set from another device or from the
owner's messaging DM.

## `pulse create`

One optional field is added.

| Field | Meaning |
|---|---|
| `deliver_to` | The chat the wake fires in, written as a `send_message` target: `platform:name`. Omitted, the wake fires in the arming chat. |

The reminder above:

```json
{"action":"create","title":"Trash","note":"Remind them to take out the trash.","trigger":{"kind":"at","after":"15m"},"owner_asked":true,"deliver_to":"converse:Master"}
```

Any wake kind may have a destination: a one-time reminder, a recurring one, or
a watcher that reports in another room.

### Resolving the destination

`deliver_to` is resolved once, when the wake is created, through the Hermes
channel directory: the same names and aliases `send_message` accepts. The wake
stores the resolved platform, chat, and session.

| Situation | Result |
|---|---|
| Resolves to one chat on a listed platform | Created. The receipt names the destination: "Reminder set for 15 minutes from now in Master." |
| Platform not in `destination_platforms` | Refused: `destination_not_allowed`. |
| No such chat, or it has never had a conversation | Refused: `destination_unknown`. |
| More than one chat matches | Refused: `destination_ambiguous`, listing the matches so the agent can ask. |

Renaming a device afterwards does not move the wake.

## Firing

The wake text is injected into the destination's session and runs as a turn
there, on that chat's model, exactly as a same-chat wake does. The wake text
says which chat armed it and that the person there may not know about it, so
the agent states the reminder plainly. `pulse respond` in that turn works as
usual, and a follow-up armed in that turn belongs to the destination chat.

When the destination cannot be reached, for example a voice device that is not
connected, the wake fires in the arming chat instead and says where it was
meant for. It fires once, in one place.

## Seeing and changing a wake

A wake with a destination appears in `pulse list` and `/pulse status` in both
chats, marked with the other end: "set from Kitchen" or "fires in Master".
Either chat can update, pause, resume, or cancel it.

## Limits

| Limit | Applies to |
|---|---|
| Turns per day, cost, `max_active` | The arming chat. |
| Quiet hours, busy chat, wake spacing | The destination. |
| Message cap, unanswered mute | The destination. |

A reminder the owner asked for (`owner_asked`) is not muted or capped in the
destination, as in its own chat. The one-wake-in-flight and
duplicate-delivery guarantees are unchanged: each fire is one durable claim.

## Not in Cadence: countdown tones

A timer that shows a countdown and ends with a tone is the voice server's
`countdown` tool, which the agent calls directly. Cadence delivers reminders
as turns; it does not ring devices.

## What Cadence needs from outside

- **Channel directory entries for voice devices.** Each device must be listed by
  its device name, so `converse:Master` resolves.
- **Whether a chat can be reached now.** Needed to fall back to the arming chat.
- **`inject_message` with another session's key.** Hermes already provides this.

## Invariants to test

- With `destination_platforms: []`, every `deliver_to` is refused and no wake
  fires outside its arming chat.
- A destination on an unlisted platform, in another profile, or in a group chat
  is refused.
- An ambiguous or unknown destination creates nothing.
- A destination wake fires once, in the destination only.
- An unreachable destination fires once, in the arming chat only.
- A follow-up armed during a destination turn belongs to the destination chat.
- Cancelling from either chat stops the wake for both.
- Quiet hours in the destination hold the wake.
