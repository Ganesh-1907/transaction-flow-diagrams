#!/usr/bin/env python3
"""
Transaction Flow Diagram Converter
Converts English-like YAML flow definitions into a Mermaid.js diagram (.mmd) and a self-contained
HTML preview (.html). Also builds index.html from flows.json. Everything is written to docs/.
Same idea as workflow-diagram-tool: the HTML page draws the diagram in the browser with Mermaid.

Supports:
- frontend_screen subtypes: rx_screen, bx_screen (the teacher's BX page)
- backend_service subtypes: bx_service, caps_service
- db_row subtypes: participant_row, transaction_row (transaction rows carry a state)
- notification subtype: email
- marker subtype: start (green circle that shows where the flow starts)
- optional context per node (rendered as subtitle), optional group (draws a box around table rows)
- counts table (rows INSERTed / UPDATEd per table) and notes under the diagram
- steps table (what each step writes) and bullet points under the diagram
- boxes: a titled box under the diagram (for example "Built URL"); each line is text or {text, code}
- links: named, coloured links (id, name, color). A box line with `link: <id>` shows the name as a coloured
  label; an edge with `link: <id>` shows the same name in the same colour on the arrow
- layout: optional, "dagre" (default) or "elk". ELK routes the lines around the boxes, for busy diagrams
"""

import argparse
import html
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

import yaml

VALID_NODE_TYPES = {"frontend_screen", "backend_service", "db_row", "notification", "marker"}
VALID_SUBTYPES = {
    "frontend_screen": {"rx_screen", "bx_screen"},
    "backend_service": {"bx_service", "caps_service"},
    "db_row": {"user_row", "participant_row", "transaction_row"},
    "notification": {"email"},
    "marker": {"start"},
}
VALID_STATES = {"PENDING", "PROCESSING", "CONFIRMED", "FAILED", "NOT_RECEIVED", "NONE"}
VALID_HIGHLIGHTS = {"problem", "expected"}
VALID_EDGE_STYLES = {"solid", "dashed", "hidden"}
# "hidden" = a layout helper that is not drawn: a transparent line with an invisible label. ELK gives every
# labelled arrow its own row, so this keeps a box level with boxes that are entered by a labelled arrow.
HIDDEN_LABEL = "<span style='visibility:hidden'>.</span>"
HIDDEN_LABEL_CSS = '.edgeLabel:has(span[style*="visibility:hidden"]) { opacity: 0; }'
LINK_ID = re.compile(r"^[A-Za-z0-9_-]+$")
HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
VALID_LAYOUTS = {"dagre", "elk"}

# The script block of the HTML page. "dagre" is Mermaid's built-in layout. "elk" routes the lines around
# the boxes and keeps side-by-side groups in a stable order; its versions are pinned on purpose.
MERMAID_SCRIPTS = {
    "dagre": """<script type="module">
  import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs";
  mermaid.initialize({ startOnLoad: true, theme: 'default', flowchart: { useMaxWidth: false } });
</script>""",
    "elk": """<script type="module">
  import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@11.17.2/dist/mermaid.esm.min.mjs";
  import elkLayouts from "https://cdn.jsdelivr.net/npm/@mermaid-js/layout-elk@0.2.3/dist/mermaid-layout-elk.esm.min.mjs";
  mermaid.registerLayoutLoaders(elkLayouts);
  mermaid.initialize({ startOnLoad: true, theme: 'default', layout: 'elk',
                       flowchart: { useMaxWidth: false, curve: 'linear', nodeSpacing: 60, rankSpacing: 80 } });
</script>""",
}

# Mermaid shape per subtype: rectangle, double bracket, cylinder (table row), rounded (email)
SHAPES = {
    "rx_screen": ('["', '"]'),
    "bx_screen": ('["', '"]'),
    "bx_service": ('[["', '"]]'),
    "caps_service": ('[["', '"]]'),
    "participant_row": ('[("', '")]'),
    "transaction_row": ('[("', '")]'),
    "user_row": ('[("', '")]'),
    "email": ('(["', '"])'),
    "start": ('(("', '"))'),
}
NODE_CLASS = {
    "rx_screen": "rxScreen",
    "bx_screen": "bxScreen",
    "bx_service": "bxService",
    "caps_service": "capsService",
    "participant_row": "participantRow",
    "transaction_row": "txNone",
    "user_row": "userRow",
    "email": "email",
    "start": "startNode",
}
CLASS_DEFS = {
    "rxScreen": "fill:#ffcdd2,stroke:#b71c1c,stroke-width:2px",
    "bxScreen": "fill:#e0f7fa,stroke:#006064,stroke-width:2px",
    "bxService": "fill:#c8e6c9,stroke:#1b5e20,stroke-width:2px",
    "capsService": "fill:#eceff1,stroke:#37474f,stroke-width:2px",
    "userRow": "fill:#ede7f6,stroke:#4527a0,stroke-width:2px",
    "participantRow": "fill:#e3f2fd,stroke:#0d47a1,stroke-width:2px",
    "txPending": "fill:#fff59d,stroke:#f9a825,stroke-width:2px",
    "txProcessing": "fill:#b3e5fc,stroke:#0277bd,stroke-width:2px",
    "txConfirmed": "fill:#a5d6a7,stroke:#2e7d32,stroke-width:2px",
    "txFailed": "fill:#ef9a9a,stroke:#c62828,stroke-width:2px",
    "txNotReceived": "fill:#ffccbc,stroke:#bf360c,stroke-width:2px",
    "txNone": "fill:#f5f5f5,stroke:#9e9e9e,stroke-width:2px",
    "email": "fill:#ffe0b2,stroke:#e65100,stroke-width:2px",
    "startNode": "fill:#2e7d32,stroke:#1b5e20,stroke-width:3px,color:#fff",
    "problem": "fill:#ffebee,stroke:#c62828,stroke-width:3px,stroke-dasharray:6 3",
    "expected": "fill:#c8e6c9,stroke:#2e7d32,stroke-width:3px",
}
# legend: (css class used in the HTML legend, text, mermaid class)
LEGEND = [
    ("rxScreen", "rx screen", "rxScreen"),
    ("bxScreen", "BX screen (teacher)", "bxScreen"),
    ("bxService", "BX API / webhook", "bxService"),
    ("capsService", "CAPS", "capsService"),
    ("userRow", "users row", "userRow"),
    ("participantRow", "program_participant row", "participantRow"),
    ("txPending", "transaction PENDING", "txPending"),
    ("txProcessing", "transaction PROCESSING", "txProcessing"),
    ("txConfirmed", "transaction CONFIRMED", "txConfirmed"),
    ("txFailed", "transaction FAILED", "txFailed"),
    ("txNotReceived", "transaction NOT_RECEIVED", "txNotReceived"),
    ("txNone", "no row", "txNone"),
    ("email", "email", "email"),
    ("problem", "problem today", "problem"),
    ("expected", "correct / expected", "expected"),
]

HTML_STYLES = """
    body { margin: 0; padding: 20px; background: white; font-family: sans-serif; }
    h1 { text-align: center; margin: 10px 0 6px; font-size: 1.4em; }
    .summary { text-align: center; max-width: 1000px; margin: 0 auto 14px; color: #444; font-size: 0.95em; }
    .legend-box { display: flex; flex-wrap: wrap; justify-content: center; gap: 8px; padding: 10px 16px; margin: 0 auto 16px;
                  border: 2px solid #424242; border-radius: 6px; background: #fafafa; max-width: fit-content; }
    .legend-item { padding: 4px 9px; border-radius: 3px; font-size: 0.8em; font-weight: 500; }
    .mermaid { overflow: auto; margin: 10px 0; text-align: center; }
    table.counts { border-collapse: collapse; margin: 18px auto; min-width: 700px; }
    table.counts th { background: #263238; color: #fff; text-align: left; padding: 7px 12px; font-size: 0.85em; }
    table.counts td { border: 1px solid #cfd8dc; padding: 7px 12px; font-size: 0.85em; }
    .points { max-width: 1000px; margin: 14px auto; color: #444; font-size: 0.9em; line-height: 1.6; }
    .points > li { margin-top: 8px; }
    .points > li > ul { margin: 2px 0 6px; }
    .note-box { max-width: 1000px; margin: 18px auto; padding: 12px 18px; border: 2px solid #f9a825; border-radius: 6px;
                background: #fff59d; color: #333; font-size: 0.9em; line-height: 1.5; }
    .note-box h3 { margin: 0 0 8px; font-size: 1.05em; }
    .note-box p { margin: 8px 0; overflow-wrap: anywhere; }
    .link-name { display: inline-block; padding: 1px 9px; margin-right: 4px; border-radius: 10px; color: #fff; font-weight: 700; font-size: 0.95em; }
    .note-box code { display: inline-block; margin-top: 3px; padding: 2px 6px; background: rgba(255, 255, 255, 0.85); border: 1px solid #e0c94f; border-radius: 3px; font-size: 0.95em; }
    .notes { max-width: 1000px; margin: 0 auto; color: #555; font-size: 0.8em; }
"""


def auto_label(node_id: str) -> str:
    """Convert snake_case id to Title Case label. Keeps ALL_CAPS words (RX, BX, CAPS ...) as they are."""
    words = node_id.split("_")
    return " ".join(w if (w.isupper() and len(w) > 1) else w.capitalize() for w in words)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def validate_workflow(data: Any) -> List[str]:
    """Validate workflow structure and return a list of error messages."""
    errors: List[str] = []
    if not isinstance(data, dict) or "workflow" not in data:
        return ["Top-level key 'workflow' is missing."]
    wf = data["workflow"]

    if wf.get("layout", "dagre") not in VALID_LAYOUTS:
        errors.append(f"'workflow.layout' must be one of {sorted(VALID_LAYOUTS)}, not '{wf.get('layout')}'.")

    for key in ("nodes", "edges"):
        if key not in wf or not isinstance(wf[key], list):
            errors.append(f"'workflow.{key}' must be a list.")
    if errors:
        return errors

    node_ids = set()
    for idx, node in enumerate(wf["nodes"]):
        prefix = f"Node [{idx}]"
        if "id" not in node:
            errors.append(f"{prefix}: Missing 'id'.")
            continue
        nid = node["id"]
        if nid in node_ids:
            errors.append(f"{prefix}: Duplicate id '{nid}'.")
        node_ids.add(nid)

        ntype, subtype = node.get("type"), node.get("subtype")
        if ntype not in VALID_NODE_TYPES:
            errors.append(f"Node '{nid}': Invalid type '{ntype}'. Must be one of {sorted(VALID_NODE_TYPES)}.")
        elif subtype not in VALID_SUBTYPES[ntype]:
            errors.append(f"Node '{nid}': Invalid subtype '{subtype}' for '{ntype}'. "
                          f"Must be one of {sorted(VALID_SUBTYPES[ntype])}.")

        state = node.get("state")
        if state is not None:
            if state not in VALID_STATES:
                errors.append(f"Node '{nid}': Invalid state '{state}'. Must be one of {sorted(VALID_STATES)}.")
            elif subtype != "transaction_row":
                errors.append(f"Node '{nid}': 'state' is only allowed on a transaction_row node.")
        hl = node.get("highlight")
        if hl is not None and hl not in VALID_HIGHLIGHTS:
            errors.append(f"Node '{nid}': Invalid highlight '{hl}'. Must be one of {sorted(VALID_HIGHLIGHTS)}.")

    link_ids = set()
    for idx, link in enumerate(wf.get("links") or []):
        prefix = f"Link [{idx}]"
        lid = link.get("id")
        if not lid or not LINK_ID.match(str(lid)):
            errors.append(f"{prefix}: Missing or invalid 'id' (use letters, digits, _ or -).")
            continue
        if lid in link_ids:
            errors.append(f"{prefix}: Duplicate id '{lid}'.")
        link_ids.add(lid)
        if not link.get("name"):
            errors.append(f"Link '{lid}': Missing 'name'.")
        if not HEX_COLOR.match(str(link.get("color", ""))):
            errors.append(f"Link '{lid}': 'color' must be a 6-digit hex colour such as \"#1565c0\".")

    for idx, edge in enumerate(wf["edges"]):
        prefix = f"Edge [{idx}]"
        if "from" not in edge or "to" not in edge:
            errors.append(f"{prefix}: Needs both 'from' and 'to'.")
            continue
        for end in ("from", "to"):
            if edge[end] not in node_ids:
                errors.append(f"{prefix}: '{end}' node '{edge[end]}' does not exist.")
        if edge.get("style", "solid") not in VALID_EDGE_STYLES:
            errors.append(f"{prefix}: Invalid style '{edge.get('style')}'. Must be one of {sorted(VALID_EDGE_STYLES)}.")
        if edge.get("link") is not None and edge["link"] not in link_ids:
            errors.append(f"{prefix}: link '{edge['link']}' is not defined under 'links'.")

    for idx, row in enumerate(wf.get("counts") or []):
        if "table" not in row:
            errors.append(f"Count [{idx}]: Missing 'table'.")

    for idx, row in enumerate(wf.get("steps") or []):
        if "step" not in row or "table" not in row:
            errors.append(f"Step [{idx}]: Needs both 'step' and 'table'.")

    for idx, box in enumerate(wf.get("boxes") or []):
        if "title" not in box:
            errors.append(f"Box [{idx}]: Missing 'title'.")
        for line in box.get("lines") or []:
            if isinstance(line, dict) and line.get("link") is not None and line["link"] not in link_ids:
                errors.append(f"Box [{idx}]: link '{line['link']}' is not defined under 'links'.")
    return errors


def quote(text: Any) -> str:
    return str(text).replace('"', "#quot;")


def node_line(node: Dict[str, Any]) -> str:
    """Mermaid node: label, then a line and the context lines (same look as workflow-diagram-tool)."""
    ctx = node.get("context") or []
    lines = [str(ctx)] if isinstance(ctx, str) else [str(c) for c in ctx]
    parts = [node.get("label") or auto_label(node["id"])] + (["---"] + lines if lines else [])
    opener, closer = SHAPES[node["subtype"]]
    text = "\\n".join(quote(p) for p in parts)
    return f"{node['id']}{opener}{text}{closer}"


def node_class(node: Dict[str, Any]) -> str:
    if node.get("highlight"):
        return node["highlight"]
    if node.get("state"):
        return "tx" + "".join(part.capitalize() for part in node["state"].split("_"))
    return NODE_CLASS[node["subtype"]]


def link_map(wf: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """The named links of a flow, by id."""
    return {link["id"]: link for link in (wf.get("links") or [])}


def rgb(color: str) -> str:
    """'#1565c0' -> 'rgb(21,101,192)'. Mermaid treats '#' + letters + ';' as an entity code, so labels use rgb()."""
    return f"rgb({int(color[1:3], 16)},{int(color[3:5], 16)},{int(color[5:7], 16)})"


def edge_label(edge: Dict[str, Any], links: Dict[str, Dict[str, Any]]) -> str:
    """Arrow text: the link name in its colour (if the edge has a link), then the condition."""
    parts = []
    link = links.get(edge.get("link"))
    if link:
        parts.append(f"<span style='color:{rgb(link['color'])};font-weight:bold'>{quote(link['name'])}</span>")
    if edge.get("condition"):
        parts.append(quote(edge["condition"]))
    return "<br/>".join(parts)


def generate_mermaid(wf: Dict[str, Any]) -> str:
    """Generate Mermaid.js flowchart syntax."""
    lines = ["flowchart TD"]
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for node in wf["nodes"]:
        if node.get("group"):
            groups.setdefault(node["group"], []).append(node)

    done = set()
    for node in wf["nodes"]:
        group = node.get("group")
        if not group:
            lines.append(f"    {node_line(node)}")
        elif group not in done:
            done.add(group)
            lines.append(f'    subgraph grp_{slug(group)}["{quote(group)}"]')
            lines += [f"        {node_line(n)}" for n in groups[group]]
            lines.append("    end")

    links = link_map(wf)
    for edge in wf["edges"]:
        if edge.get("style") == "hidden":
            lines.append(f'    {edge["from"]} ---|"{HIDDEN_LABEL}"| {edge["to"]}')
            continue
        arrow = "-.->" if edge.get("style") == "dashed" else "-->"
        text = edge_label(edge, links)
        label = f'|"{text}"|' if text else ""
        lines.append(f"    {edge['from']} {arrow}{label} {edge['to']}")
    for idx, edge in enumerate(wf["edges"]):
        if edge.get("style") == "hidden":
            lines.append(f"    linkStyle {idx} stroke:transparent,stroke-width:0px")
            continue
        link = links.get(edge.get("link"))
        if link:
            lines.append(f"    linkStyle {idx} stroke:{link['color']},stroke-width:3px")

    lines.append("")
    for name, style in CLASS_DEFS.items():
        lines.append(f"    classDef {name} {style};")
    by_class: Dict[str, List[str]] = {}
    for node in wf["nodes"]:
        by_class.setdefault(node_class(node), []).append(node["id"])
    for cls, ids in by_class.items():
        lines.append(f"    class {','.join(ids)} {cls};")
    for group in groups:
        lines.append(f"    style grp_{slug(group)} fill:#fafcff,stroke:#78909c,stroke-dasharray:4 3;")
    return "\n".join(lines)


def box_html(box: Dict[str, Any], links: Dict[str, Dict[str, Any]]) -> str:
    """A titled box. A line is plain text, or {text, code} for a label followed by a monospace value.
    A {link, text, code} line starts with that link's name as a coloured label."""
    paragraphs = []
    for line in box.get("lines") or []:
        if isinstance(line, dict):
            link = links.get(line.get("link"))
            name = (f'<span class="link-name" style="background:{link["color"]}">{html.escape(str(link["name"]))}</span> '
                    if link else "")
            paragraphs.append(f"<p>{name}{html.escape(str(line.get('text', '')))}<br>"
                              f"<code>{html.escape(str(line.get('code', '')))}</code></p>")
        else:
            paragraphs.append(f"<p>{html.escape(str(line))}</p>")
    return f'<div class="note-box"><h3>{html.escape(str(box["title"]))}</h3>{"".join(paragraphs)}</div>'


def point_html(point: Any) -> str:
    """A bullet. Plain text, or {text, items: [...]} for a bullet with sub-bullets under it."""
    if isinstance(point, dict):
        items = "".join(f"<li>{html.escape(str(i))}</li>" for i in point.get("items") or [])
        return f"<li>{html.escape(str(point.get('text', '')))}<ul>{items}</ul></li>"
    return f"<li>{html.escape(str(point))}</li>"


def generate_html(wf: Dict[str, Any]) -> str:
    """Self-contained page (Mermaid loaded from the CDN, same as workflow-diagram-tool)."""
    title = html.escape(wf.get("name", "Transaction Flow"))
    used = {node_class(n) for n in wf["nodes"]}
    legend = "".join(f'<span class="legend-item" style="{CLASS_DEFS[cls].replace("fill:", "background:").replace("stroke:", "border:1px solid ").replace(",", ";")}">'
                     f"{html.escape(text)}</span>" for cls, text, _m in LEGEND if cls in used)
    rows = "".join(
        f"<tr><td><b>{html.escape(str(c['table']))}</b></td><td>{html.escape(str(c.get('insert', '')))}</td>"
        f"<td>{html.escape(str(c.get('update', '')))}</td><td>{html.escape(str(c.get('final_rows', '')))}</td>"
        f"<td>{html.escape(str(c.get('detail', '')))}</td></tr>" for c in (wf.get("counts") or []))
    table = (f'<table class="counts"><tr><th>Table</th><th>INSERT</th><th>UPDATE</th><th>Final rows</th><th>Detail</th></tr>{rows}</table>'
             if rows else "")
    notes = "".join(f"<p>{html.escape(str(n))}</p>" for n in (wf.get("notes") or []))
    step_rows = "".join(
        f"<tr><td><b>{html.escape(str(s['step']))}</b></td><td>{html.escape(str(s['table']))}</td>"
        f"<td>{html.escape(str(s.get('change', '')))}</td></tr>" for s in (wf.get("steps") or []))
    steps = (f'<table class="counts"><tr><th>Step</th><th>Table</th><th>Rows</th></tr>{step_rows}</table>'
             if step_rows else "")
    points = ('<ul class="points">' + "".join(point_html(p) for p in wf["points"]) + "</ul>"
              if wf.get("points") else "")
    links = link_map(wf)
    layout = wf.get("layout", "dagre")
    extra_css = HIDDEN_LABEL_CSS if any(e.get("style") == "hidden" for e in wf["edges"]) else ""
    boxes ="".join(box_html(b, links) for b in (wf.get("boxes") or []))
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>{title}</title>
<style>{HTML_STYLES}{extra_css}</style>
{MERMAID_SCRIPTS[layout]}
</head>
<body>
<div class="legend-box">{legend}</div>
<h1>{title}</h1>
<p class="summary">{html.escape(wf.get("summary", ""))}</p>
<div class="mermaid">
{html.escape(generate_mermaid(wf), quote=False)}
</div>
{table}
{boxes}
{steps}
{points}
<div class="notes">{notes}</div>
</body>
</html>"""


INDEX_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>__TITLE__</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { display: flex; height: 100vh; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
         background: #f0f2f5; overflow: hidden; }
  .sidebar { width: 270px; min-width: 270px; background: #1a1f2e; overflow-y: auto; box-shadow: 2px 0 8px rgba(0,0,0,.3); }
  .sidebar-header { padding: 24px 20px 18px; border-bottom: 1px solid rgba(255,255,255,.08); }
  .sidebar-logo { font-size: 1.2em; font-weight: 800; color: #fff; }
  .sidebar-sub { font-size: .75em; color: #8b93a7; margin-top: 6px; }
  .group-title { font-size: .7em; letter-spacing: 1px; text-transform: uppercase; color: #8b93a7; padding: 18px 20px 6px; }
  .nav-btn { display: block; width: 100%; text-align: left; background: none; border: none; color: #cfd4e2; padding: 10px 20px;
             font-size: .9em; cursor: pointer; border-left: 3px solid transparent; }
  .nav-btn:hover { background: rgba(255,255,255,.06); }
  .nav-btn.active { background: rgba(255,255,255,.1); color: #fff; border-left-color: #4fc3f7; }
  .main { flex: 1; display: flex; flex-direction: column; min-width: 0; }
  .topbar { background: #fff; padding: 14px 24px; font-weight: 600; border-bottom: 1px solid #dde1e7; }
  .content { flex: 1; position: relative; }
  .welcome { padding: 40px; }
  .welcome h2 { margin-bottom: 18px; }
  .welcome-card { display: inline-block; background: #fff; border: 1px solid #dde1e7; border-radius: 8px; padding: 14px 18px;
                  margin: 0 12px 12px 0; cursor: pointer; }
  .welcome-card:hover { border-color: #4fc3f7; }
  iframe.flow-frame { display: none; position: absolute; inset: 0; width: 100%; height: 100%; border: none; background: #fff; }
  iframe.flow-frame.visible { display: block; }
</style>
</head>
<body>
<nav class="sidebar">
  <div class="sidebar-header"><div class="sidebar-logo">__TITLE__</div><div class="sidebar-sub">__SUBTITLE__</div></div>
__NAV__
</nav>
<div class="main">
  <div class="topbar" id="topbar-title">Select a flow</div>
  <div class="content">
    <div class="welcome" id="welcome"><h2>Pick a flow</h2>__CARDS__</div>
__FRAMES__
  </div>
</div>
<script>
  function showFlow(src, label) {
    document.querySelectorAll('.nav-btn').forEach(b => b.classList.toggle('active', b.dataset.src === src));
    document.getElementById('welcome').style.display = 'none';
    document.querySelectorAll('iframe.flow-frame').forEach(f => f.classList.remove('visible'));
    const frame = document.getElementById('frame-' + src);
    if (!frame.getAttribute('src')) frame.setAttribute('src', src);
    frame.classList.add('visible');
    document.getElementById('topbar-title').textContent = label;
  }
</script>
</body>
</html>
"""


def load_flow_list(src_dir: Path) -> Dict[str, Any]:
    """flows.json is the list of flows shown in index.html. YAML files missing from it are added under 'Other'."""
    registry: Dict[str, Any] = {"title": "Transaction Flows", "subtitle": "", "flows": []}
    path = src_dir / "flows.json"
    if path.exists():
        try:
            registry.update(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError as err:
            print(f"Error: flows.json is not valid JSON: {err}", file=sys.stderr)
            sys.exit(1)
    listed = {f["file"] for f in registry["flows"]}
    for yaml_path in sorted(src_dir.glob("*.yaml")):
        if yaml_path.stem not in listed:
            registry["flows"].append({"file": yaml_path.stem, "group": "Other"})
    return registry


def generate_index(src_dir: Path, out_dir: Path) -> Path:
    registry = load_flow_list(src_dir)
    nav, cards, frames, seen_groups = [], [], [], []
    for flow in registry["flows"]:
        stem = flow["file"]
        if not (src_dir / f"{stem}.yaml").exists():
            print(f"Warning: flows.json lists '{stem}' but {stem}.yaml does not exist, skipped.", file=sys.stderr)
            continue
        page = f"{stem}.html"
        label = flow.get("label") or stem
        group = flow.get("group", "Flows")
        if group not in seen_groups:
            seen_groups.append(group)
            nav.append(f'  <div class="group-title">{html.escape(group)}</div>')
        text = html.escape(f"{flow.get('icon', '')} {label}".strip())
        click = f"showFlow('{page}', '{html.escape(label, quote=True)}')"
        nav.append(f'  <button class="nav-btn" data-src="{page}" onclick="{click}">{text}</button>')
        cards.append(f'<div class="welcome-card" onclick="{click}">{text}</div>')
        frames.append(f'    <iframe id="frame-{page}" class="flow-frame" title="{html.escape(label, quote=True)}"></iframe>')
    page_html = (INDEX_TEMPLATE.replace("__TITLE__", html.escape(registry["title"]))
                 .replace("__SUBTITLE__", html.escape(registry.get("subtitle", "")))
                 .replace("__NAV__", "\n".join(nav)).replace("__CARDS__", "".join(cards))
                 .replace("__FRAMES__", "\n".join(frames)))
    path = out_dir / "index.html"
    path.write_text(page_html, encoding="utf-8")
    print(f"Generated index: {path}")
    return path


def main():
    parser = argparse.ArgumentParser(description="Convert a transaction flow YAML to Mermaid and HTML.")
    parser.add_argument("input", nargs="?", help="Path to input YAML file (omit with --index)")
    parser.add_argument("--output-dir", default=None,
                        help="Directory for the generated files (default: ./docs next to this script)")
    parser.add_argument("--index", action="store_true", help="Only (re)build index.html from flows.json")
    args = parser.parse_args()

    here = Path(__file__).resolve().parent
    output_dir = Path(args.output_dir) if args.output_dir else here / "docs"
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.index:
        generate_index(here, output_dir)
        return
    if not args.input:
        parser.error("an input YAML file is required (or use --index)")

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: File '{input_path}' not found.", file=sys.stderr)
        sys.exit(1)
    try:
        data = yaml.safe_load(input_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as err:
        print(f"Error: {input_path.name} is not valid YAML:\n{err}", file=sys.stderr)
        sys.exit(1)

    errors = validate_workflow(data)
    if errors:
        print(f"Validation failed for {input_path.name}:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        sys.exit(1)

    wf = data["workflow"]
    stem = input_path.stem
    (output_dir / f"{stem}.mmd").write_text(generate_mermaid(wf), encoding="utf-8")
    print(f"Generated Mermaid diagram: {output_dir / (stem + '.mmd')}")
    (output_dir / f"{stem}.html").write_text(generate_html(wf), encoding="utf-8")
    print(f"Generated HTML preview: {output_dir / (stem + '.html')}")


if __name__ == "__main__":
    main()
