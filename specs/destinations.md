# Destinations: wakes that fire in another chat

A wake fires in the chat that armed it. This spec lets a wake name a different
chat to fire in, and lets a timer ring a voice device without a model turn.

It exists for a household of voice devices: "set a five-minute timer on
Bedroom" is asked in the Kitchen and rings in the Bedroom.

## What the agent can do

- Arm a wake that fires in another chat: "remind Bedroom at nine to take the
  bins out."
- Arm a timer that rings a device: "set a five-minute tea timer", "set a timer
  on Bedroom."
- See and cancel a wake from either end: Bedroom can ask how long is left on,
  or cancel, a timer the Kitchen set.

## The owner's setting

Destination isolation stays the default for every platform the owner has not
listed.

| Setting | Default | Meaning |
|---|---|---|
| `destination_platforms` | `["converse"]` | Platforms whose chats may be named as a destination. `[]` turns destinations off. |

A destination must be a DM chat on a listed platform, in the same Hermes
profile as the arming chat. The arming chat may be any chat where `pulse`
works, so a timer on Bedroom can be set from another device or from the owner's
messaging DM.

## `pulse create`

Two optional fields are added.

| Field | Meaning |
|---|---|
| `deliver_to` | The chat the wake fires in, written as a `send_message` target: `platform:name`. Omitted, the wake fires in the arming chat. |
| `ring` | Makes the wake a timer: it rings the destination device instead of running a turn. An object with optional `sound` (`alarm-1` to `alarm-4`, default `alarm-1`) and `label`. Only one-time `at` wakes can ring. |

A reminder spoken in another room:

```json
{"action":"create","title":"Bins","note":"Remind them to take the bins out.","trigger":{"kind":"at","at":"21:00"},"owner_asked":true,"deliver_to":"converse:Bedroom"}
```

A timer on the device that asked:

```json
{"action":"create","title":"Tea","note":"Tea timer.","trigger":{"kind":"at","after":"5m"},"owner_asked":true,"ring":{"label":"tea"}}
```

A timer on another device:

```json
{"action":"create","title":"Tea","note":"Tea timer.","trigger":{"kind":"at","after":"5m"},"owner_asked":true,"deliver_to":"converse:Bedroom","ring":{"label":"tea"}}
```

### Resolving the destination

`deliver_to` is resolved once, when the wake is created, through the Hermes
channel directory: the same names and aliases `send_message` accepts. The wake
stores the resolved platform, chat, and session.

| Situation | Result |
|---|---|
| Resolves to one chat on a listed platform | Created. The receipt names the destination: "Tea timer set for 5 minutes on Bedroom." |
| Platform not in `destination_platforms` | Refused: `destination_not_allowed`. |
| No such chat, or it has never had a conversation | Refused: `destination_unknown`. |
| More than one chat matches | Refused: `destination_ambiguous`, listing the matches so the agent can ask. |
| `ring` on a chat that is not a voice device | Refused: `cannot_ring`. |

Renaming a device afterwards does not move the wake.

## Firing

### An ordinary wake

The wake text is injected into the destination's session and runs as a turn
there, on that chat's model, exactly as a same-chat wake does. The wake text
says which chat armed it. `pulse respond` in that turn works as usual.

### A ringing wake

No turn runs. At the deadline Cadence calls the voice server's `ring_alarm` tool
with the destination device, `sound`, and `label`.

| `ring_alarm` result | Outcome |
|---|---|
| `sent` or `queued` | The wake is done. |
| `not_attached` | The device is offline. Cadence runs one ordinary wake in the arming chat saying the timer finished and the device could not ring. |
| Any error | Retried on the engine's normal error ladder, then handled as `not_attached`. |

A ringing wake that fires more than 5 minutes late, for example after a restart,
does not ring. It is handled as `not_attached`.

Dismissing the alarm is between the device and the voice server. Cadence is not
told and does not need to be.

## Seeing and changing a wake

A wake with a destination appears in `pulse list` and `/pulse status` in both
chats, marked with the other end: "set from Kitchen" or "rings on Bedroom".
Either chat can update, pause, resume, or cancel it.

## Limits

| Limit | Ordinary wake with a destination | Ringing wake |
|---|---|---|
| Turns per day, cost, `max_active` | Charged to the arming chat. | Counts toward `max_active` only; it uses no turn. |
| Quiet hours | The destination's. | Not held: a timer the owner set rings on time. |
| Busy chat, wake spacing | The destination's. | Not held. The voice server queues the alarm behind the current exchange. |
| Message cap, unanswered mute | The destination's. | Not applied. |

The one-wake-in-flight and duplicate-delivery guarantees are unchanged: each
fire is still one durable claim, and a ringing wake calls `ring_alarm` at most
once per claim.

## What Cadence needs from outside

- **Channel directory entries for voice devices.** Each device must be listed by
  its device name, so `converse:Bedroom` resolves.
- **`ring_alarm` callable outside a turn.** Cadence calls it from the poller, with
  an explicit device.
- **`inject_message` with another session's key.** Hermes already provides this.

## Invariants to test

- With `destination_platforms: []`, every `deliver_to` is refused and no wake
  fires outside its arming chat.
- A destination on an unlisted platform, in another profile, or in a group chat
  is refused.
- An ambiguous or unknown destination creates nothing.
- A destination wake fires once, in the destination only.
- A ringing wake runs no model turn and calls `ring_alarm` once.
- `not_attached` produces exactly one turn in the arming chat and no ring later.
- A ringing wake more than 5 minutes late does not ring.
- Cancelling from either chat stops the wake for both.
- Quiet hours in the destination hold an ordinary wake and do not hold a ring.
