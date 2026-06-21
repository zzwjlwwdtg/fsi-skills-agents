"""Extract a Claude Code JSONL session into readable Markdown."""
import json
import sys
from pathlib import Path


def block_to_text(block: dict) -> str:
    t = block.get("type")
    if t == "text":
        return block.get("text", "")
    if t == "thinking":
        return f"_(thinking)_ {block.get('thinking', '')}"
    if t == "tool_use":
        name = block.get("name", "?")
        inp = block.get("input", {})
        # Compact tool input preview
        preview = json.dumps(inp, ensure_ascii=False)
        if len(preview) > 800:
            preview = preview[:800] + " …[truncated]"
        return f"**[tool_use: {name}]**\n```json\n{preview}\n```"
    if t == "tool_result":
        content = block.get("content", "")
        if isinstance(content, list):
            parts = []
            for c in content:
                if isinstance(c, dict):
                    parts.append(c.get("text", str(c)))
                else:
                    parts.append(str(c))
            content = "\n".join(parts)
        content = str(content)
        if len(content) > 1500:
            content = content[:1500] + " …[truncated]"
        return f"**[tool_result]**\n```\n{content}\n```"
    return f"[{t}] {json.dumps(block, ensure_ascii=False)[:200]}"


def extract(jsonl_path: Path, md_path: Path) -> None:
    out_lines: list[str] = []
    out_lines.append(f"# Session: {jsonl_path.stem}\n")
    out_lines.append(f"_Source: `{jsonl_path}`_\n")

    msg_count = 0
    with jsonl_path.open("r", encoding="utf-8") as f:
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue
            try:
                ev = json.loads(raw)
            except json.JSONDecodeError:
                continue

            etype = ev.get("type")
            ts = ev.get("timestamp", "")

            if etype in ("user", "assistant"):
                msg = ev.get("message", {})
                role = msg.get("role", etype)
                content = msg.get("content", "")
                out_lines.append(f"\n---\n\n## {role.upper()}  _({ts})_\n")
                if isinstance(content, str):
                    out_lines.append(content)
                elif isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict):
                            out_lines.append(block_to_text(block))
                        else:
                            out_lines.append(str(block))
                msg_count += 1
            elif etype == "summary":
                summary = ev.get("summary", "")
                out_lines.append(f"\n> **[summary]** {summary}\n")
            # Skip: file-history-snapshot, attachment, system

    md_path.write_text("\n".join(out_lines), encoding="utf-8")
    print(f"Wrote {msg_count} messages -> {md_path}  ({md_path.stat().st_size/1024:.1f} KB)")


if __name__ == "__main__":
    project_dir = Path("C:/Users/masa/.claude/projects/f--fsi-skills")
    out_dir = Path("f:/fsi-skills/extracted_sessions")
    out_dir.mkdir(exist_ok=True)
    targets = [
        "c4097393-c9a0-43ec-a572-062932a3ed54.jsonl",
        "c85f6a3d-242a-47cf-9740-a2593ee185d6.jsonl",
    ]
    for name in targets:
        src = project_dir / name
        dst = out_dir / (src.stem + ".md")
        extract(src, dst)
