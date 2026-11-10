# Transaction Flow Diagram Tool

Same idea as `workflow-diagram-tool`: describe a flow in plain English (YAML) and get a **Mermaid diagram** (`.mmd`) and an **HTML page** that draws it in the browser. This one shows how rows are created in `program_participant` and `program_participant_transaction` (T1, T2, T3 ...) for each payment scenario.

## Quick Start

One command to build everything and open `outputs/index.html` in your browser:

```bash
cd /home/ganesh/Desktop/bx/transaction-flow-diagrams && ./transaction_flow.sh --open
```

Other ways to run it:

```bash
./transaction_flow.sh                          # build all YAML files + outputs/index.html (no browser)
./transaction_flow.sh registration-sale        # build one flow (with or without .yaml)
./transaction_flow.sh registration-sale --open # --open (or -o) works with any of the above
```

Without `--open`, open `outputs/index.html` in a browser yourself. `--open` uses `xdg-open` on Linux and `open` on macOS. The first run creates the Python `venv` and installs `requirements.txt` automatically. The HTML pages load Mermaid from the internet (CDN), exactly like `workflow-diagram-tool`, so you need internet to see the diagrams.

## Folder

| File | Edit it? | What it is |
|---|---|---|
| `*.yaml` | **yes** | one file per flow |
| `flows.json` | **yes** | the list shown in `outputs/index.html` (label, group, icon) |
| `transaction_flow.sh` | no | builds everything |
| `transaction_flow_converter.py` | rarely | YAML -> `.mmd` + `.html`, validation |
| `outputs/` | no | generated: `<name>.html`, `<name>.mmd`, `index.html` |

## Add a new flow

1. Copy a YAML (`cp registration-sale.yaml my-flow.yaml`) and edit it.
2. Add it to `flows.json` (optional; a YAML that is not listed shows up under "Other"):
   `{ "file": "my-flow", "label": "My flow", "group": "Registration Sale", "icon": "🧪" }`
3. Run `./transaction_flow.sh`.

## YAML format

```yaml
workflow:
  name: "Scenario title"
  summary: "One or two sentences: rows created, emails sent."
  layout: elk                     # optional: dagre (default) | elk, see "Busy diagrams" below

  links:                          # optional: named links, each with its own colour
    - id: retry                   # unique; used as `link: retry` on edges and box lines
      name: "Retry link"          # the name that is shown
      color: "#e65100"            # 6-digit hex

  nodes:
    - id: t1_insert               # unique
      label: "INSERT T1"
      type: db_row                # see the table below
      subtype: transaction_row
      context:                    # optional: a string, or a list of lines shown under the title
        - "caps id c1"
      group: program_participant_transaction   # optional: draws a box around table rows
      state: PENDING              # transaction_row only: PENDING | PROCESSING | CONFIRMED | FAILED | NOT_RECEIVED | NONE
      highlight: problem          # optional: problem (red dashed) | expected (green)

  edges:
    - from: webhook_created
      to: t1_insert
      condition: "unseen caps id"   # optional text on the arrow
      style: dashed                 # optional: solid (default) | dashed | hidden (layout helper, not drawn)
      link: retry                   # optional: shows the link name in its colour on the arrow (above the condition)

  counts:                           # table under the diagram
    - table: program_participant
      insert: "1"
      update: "7"
      final_rows: "1"
      detail: "6 flag updates + 1 balance_due update"

  steps:                            # table under the diagram: what each step writes
    - step: "Step 3, click 1"
      table: program_participant_transaction
      change: "INSERT T1 PENDING, then FAILED"

  points:                           # bullet list under the tables
    - "One short line per bullet."
    - text: "A bullet with points under it."   # {text, items} = bullet with sub-bullets
      items:
        - "First sub-point."
        - "Second sub-point."

  boxes:                            # yellow titled boxes, shown above the steps table
    - title: "Built URL"
      lines:
        - "A plain text line."
        - text: "A label line:"     # {text, code} = label with a monospace value under it
          code: "<value>/path?ref=<id>"
        - link: retry               # {link, text, code} = same, with the coloured link name in front
          text: "Sent in the retry email:"
          code: "<value>/retry-payment?ref=<id>"

  notes:
    - "Small text under the table."
```

If `label` is missing it is generated from the `id`.

## Node types

| type | subtype | Meaning | Shape / colour |
|---|---|---|---|
| `frontend_screen` | `rx_screen` | an rx page or click | rectangle, pink |
| `frontend_screen` | `bx_screen` | a BX page the teacher uses | rectangle, light cyan |
| `backend_service` | `bx_service` | BX API or webhook | double bracket, green |
| `backend_service` | `caps_service` | CAPS (create-order, rescue service) | double bracket, grey |
| `db_row` | `user_row` | a `users` table row | cylinder, purple |
| `db_row` | `participant_row` | a `program_participant` row | cylinder, blue |
| `db_row` | `transaction_row` | a `program_participant_transaction` row | cylinder; PENDING yellow, PROCESSING blue, CONFIRMED green, FAILED red, NOT_RECEIVED orange, NONE grey |
| `notification` | `email` | an email that is sent | rounded, orange |
| `marker` | `start` | where the flow starts (point it at the first step) | circle, green |

## Validation

The converter stops with a message that names the node or edge when: an `id` is missing or duplicated, a `type`/`subtype` is not in the table, `state` is used on a node that is not a `transaction_row`, an edge points to a node that does not exist, an edge or box line uses a `link` that is not defined under `links`, a link has no `name` or no 6-digit hex `color`, `layout` is not `dagre` or `elk`, or `flows.json` is not valid JSON.

## Extending

New box kind: add the subtype to `VALID_SUBTYPES`, `SHAPES`, `NODE_CLASS` and `CLASS_DEFS` in `transaction_flow_converter.py`.

## Busy diagrams (`layout: elk`)

The default layout (`dagre`) sometimes draws a line straight through a box when a flow has several side-by-side groups. Add `layout: elk` under `workflow:` to use the ELK layout instead: it routes the lines around the boxes and keeps side-by-side groups in a stable left-to-right order. The page then loads Mermaid 11 and the ELK plugin from the CDN (versions are pinned in `MERMAID_SCRIPTS` in `transaction_flow_converter.py`). Flows without `layout` are not affected.

To keep boxes level in one row, give them the same entry: a box that sits under a shared step is placed one row lower than a box entered from further up. If one box still lands higher than its neighbours, add a layout-only edge `style: hidden` from the shared step to that box (not drawn). `event-registration.yaml` does this to keep the FREE box level with the PAID and SPECIAL CASE boxes.

## Where the facts come from

Code reading of `rx`, `bx-be-nestjs` and `caps-be` on `origin/dev` (webhook `POST /pf/programs/participants/payment-registration`, CAPS `create-order` and the rescue service `GET /rescue-service/2`). `registration-sale` was last checked on 2026-11-03; the Thank you link and Fail link of `additional-sale` on 2026-11-04 (rx `confirm-payment`, `failed` and `thankyou` pages). The `event-registration` flow (free, paid, paid with zero fee) was checked on 2026-11-04 in rx (`SingleRegistration*` pages, `confirm-payment`, `thankyou`) and bx-be-nestjs (`rx-participant-registration.service` and the payment webhook). The `event-group-registration` flow (group of 3: free, paid, paid with zero fee) was checked on 2026-11-05 in rx (`groupParticipantRegistration` pages, `action-required`, `confirm-payment`, `thankyou`) and bx-be-nestjs (the grouped register calls, the payment webhook and the event registration emails). They are code-derived, not run on a live system; each page's notes state the main assumption.
# transaction-flow-diagrams
