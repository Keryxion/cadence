"""Pure prompt rendering: supplied records and clock, no Hermes imports."""
import html
import json
import re

from .clock import Clock, format_timestamp
from .model import Wake, Occurrence, Session
from .policy import owner_requested

DISPATCH_HOLDS = {'busy', 'wake_spacing', 'in_flight', 'session_paused', 'provider_unavailable', 'not_before'}


def _age(seconds: float) -> str:
    minutes = max(0, int(seconds // 60))
    days, minutes = divmod(minutes, 1440)
    hours, minutes = divmod(minutes, 60)
    if days:
        return f"{days}d" + (f" {hours:02d}h" if hours else "")
    if hours:
        return f"{hours}h" + (f" {minutes:02d}m" if minutes else "")
    return f"{minutes}m"


def escape_text(text: str) -> str:
    # Only the engine header may contain a live occurrence marker.
    return html.escape(re.sub(r"⟦(?:pulse|cadence)\b", "[cadence", text), quote=False)


def render_wake(wake: Wake, occurrence: Occurrence, session: Session, *, clock: Clock,
                timezone="UTC", payload=None, governor_hint: str = "",
                late_by_s: float | None = None, trigger_summary: str = "", after_restart: bool = False,
                held_by: str = "", message_held: str = "", marker_tag: str | None = None,
                desk: str = "") -> str:
    now = clock.now()
    current = format_timestamp(now)
    tag = f" n:{marker_tag}" if marker_tag is not None else ""
    if 'continuation' in wake.trigger_json:
        scheduled = format_timestamp(float(occurrence.dedupe_key[2:]))
        text = (f"[follow_up id='{wake.id}' scheduled='{scheduled}' "
                f"current='{current}']\nFollow-up fired.")
        every = wake.trigger_json.get('every')
        if every:
            minutes, seconds = divmod(int(every), 60)
            interval = (f"{minutes}m" if minutes else "") + (f"{seconds}s" if seconds else "")
            text += (f" It fires again every {interval} while the work is underway; "
                     f"when the work is finished, cancel it with follow_up cancel='{wake.id}'.")
        return text
    source = trigger_summary or ('responsibility' if wake.managed and wake.role else wake.kind)
    fields = [f"trigger='{html.escape(source, quote=True)}'"]
    if wake.role:
        fields.append("role='true'")
    if owner_requested(wake):
        fields.append("owner_requested='true'")
    if payload is None:
        payload = occurrence.payload_json or None
    occurred = occurrence.matched_at if occurrence.matched_at is not None else occurrence.created_at or None
    if wake.kind == 'startup' and isinstance(payload, list) and payload:
        event = payload[-1]
        if isinstance(event, dict) and isinstance(event.get('started_at'), (float, int)):
            occurred = event['started_at']
            payload = None
    if late_by_s is not None:
        occurred = now - late_by_s
    if occurred is not None:
        fields.append(f"occurred='{format_timestamp(occurred)}'")
    fields.append(f"current='{current}'")
    if held_by in DISPATCH_HOLDS:
        fields.append(f"delayed_by='{held_by}'")
    elif late_by_s is not None and late_by_s >= 60:
        fields.append(f"late_by='{_age(late_by_s)}'")
    if after_restart:
        fields.append("after_restart='true'")
    mechanism = "cadence" if wake.managed else "pulse"
    lines = [f"⟦{mechanism} o:{occurrence.id} a:{occurrence.attempt}{tag}⟧ [{mechanism} {' '.join(fields)}]",
             escape_text(wake.note)]
    if wake.reason and wake.reason != wake.note:
        lines.append(f"Why: {escape_text(wake.reason)}")
    if wake.scratch:
        lines.append(f"Scratch: {escape_text(wake.scratch)}")
    if desk and (wake.role or wake.trigger_json.get('own_time')):
        lines.append(escape_text(desk))
    if occurrence.held_since is not None:
        since=format_timestamp(occurrence.held_since)
        reason={'held_unanswered':"you hadn't replied",'held_interruptions':'waiting for an interruption token','held_daily_cap':'daily cap','held_paused':'wake was paused'}.get(occurrence.held_reason,'held')
        lines.append(f'Held since {since} ({reason}); {occurrence.held_matches} matches merged.')
    if governor_hint:
        lines.append(escape_text(governor_hint))
    if payload is not None and payload != "":
        text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
        # Escape all tags, not just a literal closing fence, then bound the final
        # UTF-8 bytes so multibyte input cannot exceed the 2 KiB prompt budget.
        text = escape_text(text).encode("utf-8")[:2048].decode("utf-8", errors="ignore")
        source = html.escape(wake.kind, quote=True)
        lines += [f'<wake-payload source="{source}" trust="untrusted">', text, "</wake-payload>"]
    lines.append('Call respond with the outcome, a brief summary, and whether to notify the owner.' if wake.managed else
                 'Call pulse respond with the outcome, a brief summary, and whether to notify the owner.')
    message_labels={'unanswered':"the owner hasn't replied yet",
                    'interruption_limit':'waiting for an interruption token', 'daily_message_cap':"today's message limit"}
    if message_held in message_labels:
        lines.append(f'Messages are held right now ({message_labels[message_held]}). Your work still counts; '
                     "keep anything the owner should hear in your notes and tell them when they're back.")
    # Only the built-in check-in contacts the owner unasked, so only it says how to stop.
    if wake.trigger_json.get('builtin'):
        lines.append('If you notify, end with one line saying they can say "stop checking in" or use /cadence off.')
    return "\n".join(lines)
