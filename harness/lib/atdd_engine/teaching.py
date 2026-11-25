"""The teaching shape of the catalog (`[rule] wrong -> right . ref`, at most 300 characters) and its match."""

from __future__ import annotations

import re

MAX_CHARS = 300
SHAPE = re.compile(r"^\[(?P<rule>[^\]\n]+)\]\s+(?P<wrong>.+?)\s+->\s+(?P<right>.+?)(?:\s+\.\s+(?P<ref>\S.*))?$", re.S)
IDENT_A = re.compile(r"^(?=.*[/._=`\d-])\S+$")
IDENT_B = re.compile(r"^[A-Z][A-Z0-9-]+$")


def teach(rule: str, wrong: str, right: str, ref: str, limit: int = MAX_CHARS) -> str:
    """Build a message of the teaching shape, cut to `limit` characters (the wrong part is cut first)."""
    tail = f" -> {right} . {ref}"
    head = f"[{rule}] "
    room = limit - len(head) - len(tail)
    if room < 8:  # the right part and ref are the lesson: keep them, shorten the right part
        right = right[: max(8, limit - len(head) - len(ref) - 20)]
        tail = f" -> {right} . {ref}"
        room = limit - len(head) - len(tail)
    if len(wrong) > room:
        wrong = wrong[: max(1, room - 3)] + "..."
    return (head + wrong + tail)[:limit]


def identifiers(text: str) -> list[str]:
    """Identifier tokens of catalog term `identifier token`."""
    out = []
    for w in text.split():
        t = w.strip(",;:()\"'")
        t = t[:-1] if t.endswith(".") else t
        t = t.strip(",;:()\"'")
        if t and (IDENT_A.match(t) or IDENT_B.match(t)):
            out.append(t)
    return out


def parse(message: str) -> dict | None:
    m = SHAPE.match(message.strip())
    return m.groupdict() if m else None


def match(message: str, wrong: str, right: str, prevent: str, limit: int = MAX_CHARS) -> str | None:
    """None when `message` is a teaching match for the three parts, else what is missing (plain words)."""
    parts = parse(message)
    if parts is None:
        return "the message is not of the shape [rule] wrong -> right . ref"
    if not parts["wrong"].strip() or not parts["right"].strip():
        return "the wrong or right part is empty"
    if len(message) > limit:
        return f"the message is {len(message)} characters, over {limit}"
    low = message.lower()
    gone = [t for t in identifiers(wrong) + identifiers(right) + identifiers(prevent) if t.lower() not in low]
    if gone:
        return "the message lacks " + ", ".join(sorted(set(gone)))
    return None
