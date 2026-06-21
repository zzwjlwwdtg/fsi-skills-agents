"""Merge two Claude Code JSONL sessions, dedupe by content hash, summarize."""
import json
import hashlib
from pathlib import Path
from collections import OrderedDict


def event_signature(ev: dict) -> str | None:
    """Return a stable hash for a meaningful event, or None to skip."""
    etype = ev.get("type")
    if etype not in ("user", "assistant"):
        return None
    msg = ev.get("message", {})
    content = msg.get("content", "")
    role = msg.get("role", etype)
    # Normalize content to a string
    if isinstance(content, list):
        parts = []
        for b in content:
            if not isinstance(b, dict):
                parts.append(str(b))
                continue
            bt = b.get("type")
            if bt == "text":
                parts.append("T:" + b.get("text", ""))
            elif bt == "thinking":
                parts.append("K:" + b.get("thinking", ""))
            elif bt == "tool_use":
                parts.append(f"U:{b.get('name')}:{json.dumps(b.get('input',{}),sort_keys=True,ensure_ascii=False)}")
            elif bt == "tool_result":
                c = b.get("content", "")
                if isinstance(c, list):
                    c = "\n".join(x.get("text", str(x)) if isinstance(x, dict) else str(x) for x in c)
                parts.append("R:" + str(c)[:2000])
            else:
                parts.append(bt + ":" + json.dumps(b, ensure_ascii=False)[:200])
        norm = "\n".join(parts)
    else:
        norm = str(content)
    h = hashlib.md5((role + "|" + norm).encode("utf-8")).hexdigest()
    return h


def load_events(path: Path):
    events = []
    with path.open("r", encoding="utf-8") as f:
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue
            try:
                ev = json.loads(raw)
            except json.JSONDecodeError:
                continue
            sig = event_signature(ev)
            if sig is None:
                continue
            events.append((sig, ev))
    return events


def block_brief(block: dict, tool_cap=300, result_cap=400) -> str:
    t = block.get("type")
    if t == "text":
        return block.get("text", "").strip()
    if t == "thinking":
        return ""  # skip thinking in summary
    if t == "tool_use":
        name = block.get("name", "?")
        inp = json.dumps(block.get("input", {}), ensure_ascii=False)
        if len(inp) > tool_cap:
            inp = inp[:tool_cap] + "…"
        return f"`[tool:{name}]` {inp}"
    if t == "tool_result":
        c = block.get("content", "")
        if isinstance(c, list):
            c = "\n".join(x.get("text", str(x)) if isinstance(x, dict) else str(x) for x in c)
        c = str(c).strip()
        if len(c) > result_cap:
            c = c[:result_cap] + "…"
        return f"`[result]` {c}"
    return ""


def render_event(ev: dict) -> str:
    msg = ev.get("message", {})
    role = msg.get("role", ev.get("type"))
    ts = ev.get("timestamp", "")
    content = msg.get("content", "")
    lines = [f"\n### {role.upper()} _({ts})_"]
    if isinstance(content, str):
        lines.append(content)
    elif isinstance(content, list):
        for b in content:
            if isinstance(b, dict):
                s = block_brief(b)
                if s:
                    lines.append(s)
    return "\n".join(lines)


def main():
    base = Path("C:/Users/masa/.claude/projects/f--fsi-skills")
    a_path = base / "c4097393-c9a0-43ec-a572-062932a3ed54.jsonl"
    b_path = base / "c85f6a3d-242a-47cf-9740-a2593ee185d6.jsonl"

    a_events = load_events(a_path)
    b_events = load_events(b_path)
    print(f"A: {len(a_events)} events  |  B: {len(b_events)} events")

    a_sigs = {sig for sig, _ in a_events}
    b_sigs = {sig for sig, _ in b_events}
    common = a_sigs & b_sigs
    only_a = a_sigs - b_sigs
    only_b = b_sigs - a_sigs
    print(f"  shared: {len(common)}  only-A: {len(only_a)}  only-B: {len(only_b)}")

    # Build merged ordered list: walk A in order, append A events; then append B events
    # that are not in A, preserving B's relative order.
    seen = set()
    merged = []
    for sig, ev in a_events:
        if sig in seen:
            continue
        seen.add(sig)
        merged.append(("A", ev))
    for sig, ev in b_events:
        if sig in seen:
            continue
        seen.add(sig)
        merged.append(("B", ev))
    print(f"  merged unique: {len(merged)}")

    # Write merged Markdown
    out_dir = Path("f:/fsi-skills/extracted_sessions")
    out_path = out_dir / "MERGED_session_dedup.md"
    lines = [
        "# Merged Session (deduplicated)",
        "",
        f"Source A: `{a_path.name}` — {len(a_events)} events",
        f"Source B: `{b_path.name}` — {len(b_events)} events",
        f"Shared: {len(common)}  •  Only-A: {len(only_a)}  •  Only-B: {len(only_b)}  •  Merged unique: {len(merged)}",
        "",
        "---",
    ]
    for src, ev in merged:
        lines.append(f"\n<!-- src={src} -->")
        lines.append(render_event(ev))
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote merged -> {out_path}  ({out_path.stat().st_size/1024:.1f} KB)")

    # Also write a user-only timeline for quick scanning
    user_path = out_dir / "MERGED_user_turns_only.md"
    ulines = ["# User turns timeline (merged, deduped)\n"]
    for src, ev in merged:
        msg = ev.get("message", {})
        if msg.get("role") != "user":
            continue
        content = msg.get("content", "")
        if isinstance(content, list):
            texts = []
            for b in content:
                if isinstance(b, dict) and b.get("type") == "text":
                    texts.append(b.get("text", ""))
            text = "\n".join(texts).strip()
        else:
            text = str(content).strip()
        if not text:
            continue
        # skip tool_result-only user events (they have no text blocks)
        ts = ev.get("timestamp", "")
        ulines.append(f"- **[{ts}]** ({src}) {text[:300].replace(chr(10),' ')}")
    user_path.write_text("\n".join(ulines), encoding="utf-8")
    print(f"Wrote user-only -> {user_path}")


if __name__ == "__main__":
    main()
