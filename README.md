# Campus Customs — Multi-Agent Operations

A back-office for a small Yale campus merch shop, run by a team of five AI agents.

Three tickets sit on the desk: a student waiting on a tee, a landlord asking for rent, and a
student club asking for a bulk discount. A **Boss** agent reads each one and delegates to
**Inventory**, **Accounting**, **Facilities** and **Customer Service**. They read the shop's data
through an MCP server, prepare payments, and draft replies — but **no agent can move money or send
a message**. A person approves every payment on the dashboard, and every step of every agent's loop
is appended to an audit trail.

| Piece | What it is |
|---|---|
| `mcp_server/` | A FastMCP server with 19 tools over `data/campus_customs_new.db`. The only way anything reads or writes shop data. |
| `backend/` | FastAPI + five PydanticAI agents on **`gpt-6-luna`** via Portkey. Serves the board, runs the team, and owns the human approval step. |
| `frontend/` | A React + Vite + TypeScript dashboard: the tickets, the live agent stream, the balance, and the approve button. |
| `output/` | Everything the assignment asks for — the harness, the plan, the live run, the design notes and the audit trail. |

---

## 1. Prerequisites

- **Python 3.12+** (built and run on 3.14)
- **Node 20+** (built and run on 22)
- **A Portkey API key** with access to `gpt-6-luna`

## 2. Setup

```bash
# from the project root
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

cd frontend && npm install && cd ..
```

Then add your key:

```bash
cp .env.example .env
# open .env and set PORTKEY_API_KEY=...
```

`.env` is gitignored. The backend also accepts `PORTKEY_API_KEY` straight from the shell
environment, which always wins over the file.

## 3. Reset the database

`data/campus_customs.db` is the **original** and is never written to. `data/campus_customs_new.db`
is the **working copy** that the MCP server, the agents and the dashboard all read and write.

Resetting means copying the original over the working copy:

```bash
cp data/campus_customs.db data/campus_customs_new.db
```

Once the backend is running, the same thing is one request — and this is what the dashboard's
**Reset board** button calls:

```bash
curl -X POST http://127.0.0.1:8000/reset
```

Either way: all three tickets go back to `open`, checking goes back to **$3,400.00**, and the
workflow tables (payment requests, drafts, outcomes) are dropped — the MCP server recreates them
empty on its next call. `output/audit_trail.json` is append-only and is deliberately **not**
touched by a reset, so the history of earlier runs survives.

> **Note on what ships in this repo:** `data/campus_customs_new.db` is committed in the *resolved*
> end state of the documented run — three resolved tickets and $160.00 in checking — so it matches
> `output/resolved_tickets.json` and `output/resolved_board.html`. Reset before running it yourself.

## 4. Start the MCP server

You do not normally start this by hand. The backend spawns it over stdio, and `.mcp.json` lets a
vibe coder (Claude Code) connect to the same server. To run it standalone — to inspect the tools,
or to point an MCP client at it:

```bash
.venv/bin/python mcp_server/server.py
```

It speaks MCP over stdio and prints nothing on success. See `mcp_server/README.md` for the full
tool list.

## 5. Run the FastAPI backend

```bash
cd backend
../.venv/bin/uvicorn main:app --reload --port 8000
```

- Health check: <http://127.0.0.1:8000/health>
- Interactive API docs: <http://127.0.0.1:8000/docs>

The backend starts its own MCP server process and keeps it for the life of the API. CORS is open to
`localhost:5173` and nothing else.

**The routes:**

| Route | What it does |
|---|---|
| `GET /tickets` | Every ticket and its status |
| `GET /tickets/{id}` | One ticket with its approvals, drafts and outcome |
| `POST /tickets/{id}/run` | Hands one open ticket to the agent team |
| `GET /events` | Recent agent steps and tool calls |
| `GET /events/stream` | The same steps live over SSE |
| `GET /approvals` | Payment requests and their status |
| `POST /approvals/{id}/approve` | A human approves — cash leaves `cash_accounts` |
| `POST /approvals/{id}/reject` | A human declines — nothing moves |
| `GET /cash` | Checking balance and what is already promised |
| `POST /reset` | Restores the working database from the original |

You can also run one ticket from the command line, without the API or the dashboard:

```bash
cd backend && ../.venv/bin/python agents.py 101
```

## 6. Launch the React dashboard

With the backend already running, in a second terminal:

```bash
cd frontend
npm run dev
```

Open <http://localhost:5173>. Pick a ticket, press **Run the team**, and watch the agents work in
the centre column. When a payment needs a person, type your name in **Needs a human** and approve
or decline it.

---

## Doing a full three-ticket run

This is the sequence that produced everything in `output/`:

1. **Reset**, so the run starts from a known state:
   ```bash
   curl -X POST http://127.0.0.1:8000/reset
   ```
   Checking should read **$3,400.00** and all three tickets should be `open`.
2. **Run ticket 101** on the dashboard. The team finds the size S tee is out of stock and that an
   overdue $840.00 invoice is blocking the vendor. **Approve the $840.00** — this also unblocks
   Bulldog Print Co for the rest of the run.
3. **Run ticket 102.** Facilities checks the rent notice against the lease. **Approve the
   $2,400.00.** Checking is now $160.00.
4. **Run ticket 103.** With $160.00 left, the $264.00 hoodie restock is unaffordable, so no payment
   is requested and the ticket resolves on its own.

All three end at `resolved`, checking ends at **$160.00**, and `output/audit_trail.json` grows by
about 108 entries.

**Order matters.** Paying invoice 501 first clears the shop's only apparel vendor; paying rent
second protects a fixed obligation. Run 103 before 102 and the $264.00 restock becomes affordable —
leaving the shop $104.00 short of its rent.

---

## What's in `output/`

| File | What it is |
|---|---|
| `harness.md` | The map of the whole system: tables, tools, agents, routes, dashboard, safety, and the live run |
| `mcp_smoke.json` | The first three MCP tools called live, with the raw database output they returned |
| `desk_tickets.html` | Per-ticket **Expected** plan vs. **Actual** run, the cash math, and the reflection. Open it in a browser |
| `design.md` | Why the dashboard looks and behaves the way it does |
| `resolved_tickets.json` | The structured record of the full three-ticket run |
| `resolved_board.html` | That run narrated against real screenshots of the dashboard |
| `screenshots/` | The eight screenshots `resolved_board.html` uses |
| `audit_trail.json` | Append-only. Every model turn, tool call, hand-off and human decision, ever |
| `github_url.txt` | The public repo link |

---

## The rules this shop runs on

- **A human approves every payment.** Agents can only create *pending* requests. The one tool that
  moves cash, `pay_approved_request`, is in no agent's toolset — only the backend's approval route
  calls it, and it refuses an approver named after an agent.
- **No negative balances.** Request tools refuse what checking can't cover, and the pay step
  re-checks the balance inside a locked transaction.
- **No invented numbers.** Every amount comes from the database. Agents never type a dollar figure
  into a payment tool.
- **"Today" is the shop's today.** All overdue and due-soon maths uses `desk.date_today`
  (2026-08-31), never the real clock.
- **Nothing leaves the shop.** There are no email, phone or vendor tools. Customer messages are
  drafts on the board.
- **One model.** Every agent uses `gpt-6-luna` and nothing else.

---

## Layout

```
.
├── AI_prompts.md            what I typed to the vibe coder, per problem
├── README.md
├── requirements.txt
├── .env.example
├── .gitignore
├── .mcp.json                lets a vibe coder connect to the MCP server
├── data/
│   ├── campus_customs.db        original, never written to
│   └── campus_customs_new.db    working copy
├── mcp_server/
│   ├── server.py            19 FastMCP tools over the working copy
│   └── README.md
├── backend/
│   ├── main.py              FastAPI routes
│   ├── agents.py            the five-agent team and the ticket runner
│   ├── models.py            shared data types
│   ├── mcp_tools.py         each agent's MCP connection and allowed tools
│   ├── audit.py             append-only audit trail
│   └── prompts/             boss · inventory · accounting · facilities · customer_service
├── frontend/
│   └── src/                 React + Vite + TypeScript dashboard
└── output/                  every deliverable
```

---

MGT 409 · AI Foundations for Managers · Homework 5
