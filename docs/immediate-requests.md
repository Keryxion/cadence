# Immediate Session Requests

Conversations communicate about arbitrary tasks using `request names`, `rename`,
`ask`, `answer`, and `list`. `/pulse name <name>` names the invoking conversation.
The receiver uses its normal context, tools and permissions. Transport is
immediate, not scheduled cross-session delivery.

Design reference: [Claude Code cross-session messaging](https://code.claude.com/docs/en/cross-session-messaging).
Discover conversations, send concise text, let the receiver act in its own
context. Cadence deliberately differs by requiring explicit self-naming, not
automatic enrollment. No machine sockets or extra access settings are copied.

## Names Are Opt-In

`names` is available before self-naming. Each entry has `title` (host display
label or platform fallback), `name` (chosen address or null) and `addressable`.
`reachable` is present only when the host's own admission check could be
consulted: `true` means an ask sent now would be admitted, `false` that it would
be refused. Unnamed conversations are discoverable but cannot be addressed.
A title, session ID or route key is never an address fallback: "There is a
conversation titled Kitchen, but it has not chosen the name Kitchen yet."
Listing never enrolls anyone. `rename` enrolls only the invoking conversation.
Names are 1-40 characters after trimming, with no control characters, and
case-insensitively unique within this profile. Punctuation such as a colon or an
apostrophe is ordinary text; a straight and a typographic apostrophe are different
characters. A name belongs to the conversation, not to one session: it survives
`/new` and a gateway restart, and routing never uses a stored session ID.
Both participants must choose names to communicate. Renaming preserves existing
requests because routing uses stable internal identity.

The directory imports the gateway routing index within this profile, supplemented
by conversations Cadence has already observed. Older hosts may provide only a
platform label. No operator owner/actor mapping or DM restriction applies.
Host profile-serving and injection consent boundaries still apply.

## General Ask And Answer

1. Each participant names itself: `request {action:rename,name:Kitchen}`.
2. A named source calls `request {action:ask,to:Kitchen,note:"Inspect the project and report findings."}`.
3. The recipient uses normal tools and permissions, then calls `request answer`
   with the supplied ID, `outcome` (`accepted`, `declined`, `counter`), a summary,
   and `notify:false`.
4. The source confirms success only after an `accepted` answer. Queue acceptance
   alone does not mean the work was done.

A device countdown uses the recipient's own countdown tool; that is an example,
not a task restriction. There is no artificial request-turn tool allowlist.
Communication does not mint `owner_asked` scheduling authority; existing pulse
policy remains intact.

Ordinary acknowledgement and setup speech may happen in the recipient's own chat.
`notify:false` suppresses the final reply where the host honors the transform;
it cannot retract interim streamed output or tool speech. There is no silence
guarantee and no global stream hold or buffering. This slice accepts only
`notify:false`. One-way tell, broadcasts and nested asks are not implemented.

## Host Support And Evidence

Requests need nothing from the host beyond `inject_message` and a turn id in
`pre_llm_call`, so they work on every supported Hermes version. Each delivery
carries the request's durable ID and a random single-use token. Cadence accepts
it only in the conversation it was addressed to and only once; a wrong token, a
wrong conversation or a replay is refused, and the reason is logged.

Real-loader integration uses installed Hermes PluginContext injection and bound
MessageEvent hooks with an in-memory gateway injector. Optional
`CADENCE_CONVERSE_ROOT` imports actual countdown implementation with an in-memory
attachment and disabled scheduling, then routes its answer back to the source.
Ordinary direct streaming callbacks remain immediate. No model, live socket,
physical device, install or restart is exercised.

Any session the host can route an injected message to is supported. There is
no cross-profile transport.

## Ask States

Each `ask` result is exactly one of three states, in its `state` field:

| `state` | Shape | Meaning | Asking again |
| --- | --- | --- | --- |
| `awaiting_answer` | `ok:true`, `request` | The host took the request for the target. Not success yet. | Wait for the answer. |
| `not_delivered` | `error:not_delivered`, `reason`, `detail`, `retry_safe:true` | The target never got it and did nothing. No request is recorded. | Safe once the reason is fixed. |
| `unknown` | `error:unknown`, `request`, `retry_safe:false` | The host failed mid-handoff; the target may have acted. | Check the target first. |

`reason` is `target_not_ready` (the host would refuse it: see below),
`cadence_unavailable` (off, paused, or injection not allowed) or `host_refused`
(`inject_message` returned false, so nothing was scheduled). A name nobody chose
is `error:unknown_name`, which is not a state of any request.

Hermes's `inject_message` returns before the gateway decides: true means the
turn was scheduled, and a refusal by the session authority afterwards is only
logged. The authority admits a plugin turn only into a conversation whose current
session already holds a human message, so a conversation just started with `/new`
(or reset) cannot be asked anything until someone speaks to it. Cadence asks the
host that same question before sending and fails at once with `target_not_ready`.
On a host without a session authority there is no such refusal and no check.

## Durable Outcomes

SQLite stores IDs, stable routes, originating turns, note fingerprints, nonce,
target claim, outcome and answer claim. Claims commit before host injection;
restart never resubmits a claimed delivery. Crashes can lose delivery,
deliberately favoring no repeated action over availability.

After 60 seconds, a request the target's turn never claimed ends `not_delivered`:
the target did nothing, a late delivery is refused, and asking again is safe. A
request the target did receive but never answered ends `unknown`. Either way one
notice is attempted to the asker. After `unknown` the target may have acted. Never retry, paraphrase to evade
deduplication, or do the work locally without checking. Known acceptance remains
accepted if return delivery is unknown; `list` exposes `answer_state` separately.
External effects are not exactly once or rolled back by this protocol.

Duplicates are scoped to stripped note + source + target + originating host turn,
including after restart. A later real turn may legitimately repeat the same note.
One unfinished ask per directional pair is refused rather than queued. This slice
adds no counter chaining, linked-wake failure reporting, cost quota or pruning.
