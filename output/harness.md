# Campus Customs Harness

The map of what the Campus Customs agent team works with: the data, the MCP tools, the agents, the API routes, the dashboard, the safety rules, and what happened when all three tickets were actually run.

## Database

- **Original:** `data/campus_customs.db` stays untouched and is only used to reset.
- **Working copy:** `data/campus_customs_new.db` is the copy the MCP server and backend read and write.
- **Shop "today":** `desk.date_today` = **2026-08-31**. All overdue and due-soon checks use this date, not the real clock.

## Tables

### `desk`

**Why it matters:** It holds the shop's "today," so agents use it to decide whether a bill or the rent is overdue.

| Field | Type | Notes |
|---|---|---|
| `date_today` | TEXT | Shop's current date (2026-08-31) |
| `notes` | TEXT | Free-text desk notes (empty) |

### `tickets`

**Why it matters:** This is the work queue. The Boss reads each ticket to route it, and its `sku`, `lease_id` and `invoice_id` columns point specialists to the rows they need.

| Field | Type | Notes |
|---|---|---|
| `id` | INTEGER, PK | 101, 102, 103 |
| `type` | TEXT | `customer_order`, `rent_notice`, `price_override` |
| `requester` | TEXT | Who asked (customer, landlord, student org) |
| `subject` | TEXT | Short title |
| `sku` | TEXT | Product involved → `inventory`, `pricing` |
| `size` | TEXT | Size involved → `inventory` |
| `qty` | INTEGER | Units requested |
| `lease_id` | INTEGER, FK → `leases.id` | Set on rent tickets |
| `invoice_id` | INTEGER, FK → `invoices.id` | Set when a vendor bill is tied to the ticket |
| `status` | TEXT | All three start as `open` |
| `notes` | TEXT | Request details in the requester's words |
| `created_at` | TEXT | ISO timestamp |

### `inventory`

**Why it matters:** This is the Inventory agent's record of stock by SKU and size, and where the shortfalls on tickets 101 and 103 show up.

| Field | Type | Notes |
|---|---|---|
| `sku` | TEXT, PK (with `size`) | Product code, e.g. `CC-TEE-WHITE` |
| `name` | TEXT | Product name |
| `size` | TEXT, PK (with `sku`) | `S` / `M` / `L` / `XL`, or `OS` (one size) |
| `qty` | INTEGER | Units on hand |
| `location` | TEXT | Aisle in the shop |

### `pricing`

**Why it matters:** It gives unit cost and list price per SKU, which Accounting needs to cost a restock and to see how much margin a bulk discount can give up.

| Field | Type | Notes |
|---|---|---|
| `sku` | TEXT, PK | Product code → `inventory.sku` |
| `unit_cost` | REAL | What the shop pays per unit |
| `list_price` | REAL | What the shop charges per unit |

### `vendors`

**Why it matters:** It shows who can restock what and how fast. `lead_days` sets the earliest restock date the agents can promise a customer.

| Field | Type | Notes |
|---|---|---|
| `id` | INTEGER, PK | Referenced by `invoices.vendor_id` |
| `name` | TEXT | Vendor name |
| `specialty` | TEXT | What they supply. There is no SKU column, so this is the only way to match a vendor to a product. |
| `lead_days` | INTEGER | Days from order to delivery |

### `invoices`

**Why it matters:** These are unpaid vendor bills. A vendor with an open invoice won't ship new product, so an open invoice can block a restock.

| Field | Type | Notes |
|---|---|---|
| `id` | INTEGER, PK | Referenced by `tickets.invoice_id` |
| `vendor_id` | INTEGER, FK → `vendors.id` | Who is owed |
| `amount` | REAL | Amount due |
| `due_date` | TEXT | Overdue if before `desk.date_today` |
| `status` | TEXT | `open` = unpaid |
| `description` | TEXT | What the bill is for |

### `leases`

**Why it matters:** This is Facilities' record of the shop space: the rent amount and next due date behind ticket 102.

| Field | Type | Notes |
|---|---|---|
| `id` | INTEGER, PK | Referenced by `tickets.lease_id` |
| `space_name` | TEXT | Which space |
| `landlord` | TEXT | Who is paid |
| `monthly_rent` | REAL | Rent amount |
| `next_due` | TEXT | Next rent due date |
| `notes` | TEXT | Lease notes (empty) |

### `cash_accounts`

**Why it matters:** It holds the cash the shop actually has. Every payment has to check it first and can never take it below zero.

| Field | Type | Notes |
|---|---|---|
| `name` | TEXT, PK | Account name (`checking`) |
| `balance` | REAL | Current balance |
| `date` | TEXT | Balance as-of date |

### `payments`

**Why it matters:** This is the ledger of money out. Every human-approved payment adds a row here, which makes it the audit trail for cash. It starts empty.

| Field | Type | Notes |
|---|---|---|
| `id` | INTEGER, PK | Payment id |
| `kind` | TEXT | What was paid (e.g. invoice, rent, purchase) |
| `ref_id` | INTEGER | Id of the invoice or lease paid, depending on `kind` |
| `amount` | REAL | Amount paid |
| `account` | TEXT | Paid from → `cash_accounts.name` |
| `paid_at` | TEXT | When it was paid |
| `approved_by` | TEXT | The human who approved it |

## How the open tickets link

### Ticket 101: Bulldog tee (`customer_order`, Tauhid Zaman)

- `sku` `CC-TEE-WHITE`, size `S`, qty 1 → `inventory`: **0 on hand** (Aisle B), so the order is short 1.
- `pricing`: unit cost $8.00, list $28.00.
- `invoice_id` 501 → `invoices`: **$840.00** owed to vendor 1, due 2026-08-28, status `open`. That is **3 days overdue** on 2026-08-31. Description: "Rush reprint CC-TEE-WHITE S".
- `invoices.vendor_id` 1 → `vendors`: **Bulldog Print Co** (apparel reprint), 5-day lead time. It won't ship while invoice 501 is unpaid.

### Ticket 102: Rent due (`rent_notice`, Elm City Properties)

- `lease_id` 1 → `leases`: Chapel Street shop, landlord Elm City Properties, **$2,400.00/month**, next due **2026-09-02**. That is 2 days out, so the rent is not overdue yet.
- Paying it draws on `cash_accounts.checking` and adds a row to `payments`.

### Ticket 103: Bulk hoodie discount (`price_override`, Yale AI Club)

- `sku` `CC-HOOD-NAVY`, size `M`, qty 20 → `inventory`: **8 on hand**, so the order is short 12. Other sizes on hand: S 4, L 14, XL 6.
- `pricing`: unit cost $22.00, list $58.00, so the shop makes $36.00 per hoodie at list price before any discount.
- There is no direct invoice or lease link. Bulldog Print Co is the only apparel vendor, so any restock runs into the same open invoice 501.

### Shared constraint: cash

`checking` starts at **$3,400.00** (as of 2026-08-31). Invoice 501 ($840.00) plus rent ($2,400.00) comes to $3,240.00, which leaves **$160.00**. Restocking the 12-hoodie shortfall at unit cost would cost $264.00.

## MCP tools

Server: `mcp_server/server.py` (FastMCP), over `data/campus_customs_new.db`. Overdue and due-soon math uses `desk.date_today`. Money amounts are always computed from the database and never typed in by an agent. Read tools use a query-only connection, and write tools run in a single transaction.

### Starter tools (Problem 3): one per ticket

| Tool | Reads | Unlocks | Why it's the right tool for that ticket |
|---|---|---|---|
| `get_vendor_invoice(invoice_id)` | `invoices`, `vendors`, `desk` | **101** | Ticket 101 is tied to invoice 501, and this tool shows it's an open $840.00 bill to Bulldog Print Co, 3 days overdue, which blocks the vendor from reprinting the size S tee until a human approves paying it. |
| `get_lease(lease_id)` | `leases`, `desk` | **102** | Ticket 102 points to lease 1, and this tool confirms the rent notice against the lease: $2,400.00 to Elm City Properties, due 2026-09-02, 2 days out and not yet overdue. |
| `check_stock_and_price(sku, size, qty_needed)` | `inventory`, `pricing` | **103** | The Yale AI Club wants 20 size M hoodies at a discount, and this tool shows only 8 are on hand (12 short) and that each costs $22.00 against a $58.00 list price, so the team knows how many it can fill now and how far the price can drop before it loses money. |

`check_stock_and_price` also confirms ticket 101's shortfall: the size S tee shows 0 on hand.

### All 19 tools (Problem 5)

| Tool | Tables | Used by | What it does |
|---|---|---|---|
| `check_stock_and_price` | `inventory`, `pricing` | Inventory, Accounting, Customer Service | On hand for a SKU and size, shortfall vs. `qty_needed`, other sizes, unit cost, list price |
| `get_vendor_invoice` | `invoices`, `vendors`, `desk` | Inventory, Accounting | One invoice: amount, days overdue, vendor lead time, whether the vendor is blocked |
| `get_lease` | `leases`, `desk` | Facilities | Rent, landlord, next due date, days until due |
| `get_ticket` | `tickets`, `desk`, `approval_requests`, `message_drafts`, `ticket_outcomes` | All five agents | One ticket plus everything attached to it so far |
| `list_tickets` | `tickets` | Boss | The board: every ticket and its status |
| `get_cash_balance` | `cash_accounts`, `approval_requests`, `desk` | Boss, Accounting | Checking balance, total waiting on approval, what's left after pending |
| `list_vendors` | `vendors`, `invoices`, `desk` | Inventory, Accounting | Each vendor's specialty, lead time, open invoices, blocked flag, earliest delivery |
| `list_open_invoices` | `invoices`, `vendors`, `desk` | Accounting | Every unpaid bill with days overdue |
| `quote_bulk_price` | `pricing` | Accounting, Customer Service | Discounted unit price, order total, margin, break-even discount. Refuses below-cost quotes |
| `list_approval_requests` | `approval_requests` | Boss, Accounting, Facilities | Payment and purchase requests and their status |
| `list_message_drafts` | `message_drafts` | Boss, Customer Service | Drafts saved on the board |
| `list_payments` | `payments` | Accounting | The ledger of approved payments |
| `request_invoice_payment` | `invoices`, `vendors`, `cash_accounts`, `approval_requests` | Accounting | Adds a **pending** request to pay an open invoice in full. Refuses duplicates and amounts checking can't cover |
| `request_rent_payment` | `leases`, `cash_accounts`, `approval_requests` | Accounting | Adds a **pending** request for one month's rent. Refuses duplicates and amounts checking can't cover |
| `request_purchase_order` | `vendors`, `invoices`, `inventory`, `pricing`, `cash_accounts`, `approval_requests` | Accounting | Adds a **pending** restock purchase (qty × unit cost). Refuses blocked vendors, unknown items, and amounts checking can't cover |
| `save_message_draft` | `tickets`, `message_drafts` | Customer Service | Saves a draft to the ticket's requester. Nothing is sent |
| `close_ticket` | `tickets`, `approval_requests`, `ticket_outcomes` | Backend only, after the Boss decides | Records the outcome. Status becomes `awaiting_approval` if requests are pending, otherwise `resolved` |
| `pay_approved_request` | `approval_requests`, `cash_accounts`, `payments`, `invoices`, `leases`, `tickets` | **Human approval route only** | The only tool that moves cash. Writes the `payments` row, marks the invoice paid or moves the lease's `next_due`, and refuses if cash would go negative |
| `reject_approval_request` | `approval_requests`, `tickets` | **Human approval route only** | Declines a request. No cash moves |

### Workflow tables the server adds

The server creates these in the working copy (`CREATE TABLE IF NOT EXISTS`). They hold the team's work, not shop facts. A reset to the original database removes them, and they come back empty.

| Table | Fields | Why it matters |
|---|---|---|
| `approval_requests` | `id`, `ticket_id`, `kind` (invoice / rent / purchase_order), `ref_id`, `vendor_id`, `sku`, `size`, `qty`, `payee`, `amount`, `reason`, `requested_by`, `status` (pending / paid / rejected), `created_at`, `expected_arrival`, `decided_by`, `decided_at`, `decision_note`, `payment_id` | The queue of payments waiting for a human. The board's approve button works from it |
| `message_drafts` | `id`, `ticket_id`, `recipient`, `subject`, `body`, `drafted_by`, `status`, `created_at` | Customer Service drafts stay here on the board, never sent |
| `ticket_outcomes` | `ticket_id`, `outcome`, `decided_by`, `closed_at` | The Boss's final call on each ticket |

## Agents

All five agents run on PydanticAI with **`gpt-6-luna` only**, through Portkey (`PORTKEY_API_KEY`, `https://api.portkey.ai/v1`), using the Responses API with low reasoning effort. Prompts are in `backend/prompts/`, data types in `backend/models.py`, and the team itself in `backend/agents.py`. Each agent's MCP access goes through `backend/mcp_tools.py`.

| Agent | Prompt | Job | MCP tools it can see | Returns |
|---|---|---|---|---|
| **Boss** | `boss.md` | Reads the ticket, picks who goes first and why, delegates focused jobs, checks reports, makes the final call (including discounts) | `get_ticket`, `list_tickets`, `get_cash_balance`, `list_approval_requests`, `list_message_drafts` | `BossDecision` |
| **Inventory** | `inventory.md` | Stock by SKU and size, shortfalls, which vendor can restock, lead time, blocked or not, restock cost | `get_ticket`, `check_stock_and_price`, `list_vendors`, `get_vendor_invoice` | `SpecialistReport` |
| **Accounting** | `accounting.md` | Cash, invoices, margins and discount quotes. Prepares payments and purchase orders for human approval | `get_ticket`, `get_cash_balance`, `get_vendor_invoice`, `list_open_invoices`, `list_vendors`, `check_stock_and_price`, `quote_bulk_price`, `list_approval_requests`, `list_payments`, `request_invoice_payment`, `request_rent_payment`, `request_purchase_order` | `SpecialistReport` |
| **Facilities** | `facilities.md` | Leases and rent. Checks a notice against the lease (landlord, amount, due date) before anyone pays | `get_ticket`, `get_lease`, `list_approval_requests` | `SpecialistReport` |
| **Customer Service** | `customer_service.md` | Drafts the reply to the ticket's requester using only confirmed facts. Saved on the board, never sent | `get_ticket`, `check_stock_and_price`, `quote_bulk_price`, `save_message_draft`, `list_message_drafts` | `SpecialistReport` |

### Delegation: full connectivity

Every agent has a `delegate(to, task)` tool that can reach **any** other agent. The teammate runs its own loop and returns its report to the caller. Example from a test run on ticket 102: Boss → Facilities → Accounting, with Facilities handing the rent payment prep straight to Accounting. Four rules keep it from looping:

- An agent can't delegate to itself.
- An agent can't delegate back to the teammate who handed it the work. It answers in its report instead.
- A chain can be at most 3 agents deep (e.g. Boss → Inventory → Accounting).
- A ticket gets at most 8 delegations in total.

### Ticket run

`run_ticket(ticket_id)` in `backend/agents.py` runs one ticket:

1. Reads the ticket through MCP. Only `open` tickets can run.
2. Hands it to the Boss.
3. Records the Boss's decision with `close_ticket`.

From the command line: `cd backend && ../.venv/bin/python agents.py 101`.

### Audit trail

`output/audit_trail.json` is a JSON array. Every step of every agent's loop is **appended**: earlier entries are never rewritten, and the file is never wiped. Each entry has `timestamp`, `run_id`, `ticket_id`, `agent`, `chain` (who delegated to whom), `step`, and `event`:

| `event` | What's recorded |
|---|---|
| `run_start` | The task the agent was given |
| `model_response` | What the agent said, the tools it called with their arguments, and input/output tokens |
| `tool_result` | The tool's output and whether it succeeded or was refused |
| `delegation` | Who handed what to whom |
| `retry` | A rejected tool call or output, and why |
| `final` | The agent's report or decision |
| `error` | Why a run stopped |
| `run_end` | Ticket totals: status, model requests, tokens, delegations, duration |

## API routes

`backend/main.py` is a FastAPI app over the same MCP server the agents use, so the API keeps no second
copy of the shop's rules. Boot it from `backend/`, with interactive docs at `http://127.0.0.1:8000/docs`:

```bash
cd backend && ../.venv/bin/uvicorn main:app --reload --port 8000
```

| Route | What it does |
|---|---|
| `GET /health` | Says the API is up, the MCP server is connected, and which database it is on. |
| `GET /tickets` | The board: every ticket and its status. `?status=` filters to open, awaiting_approval or resolved. |
| `GET /tickets/{id}` | One ticket with the approval requests, message drafts and final outcome attached to it. |
| `POST /tickets/{id}/run` | Hands one open ticket to the Boss and returns the run's status, decision, delegations and token totals when the team finishes. |
| `GET /events` | Recent agent steps and tool calls, each with a `seq`; `?since=` fetches only what is new and `?ticket_id=` narrows to one ticket. |
| `GET /events/stream` | The same steps live over SSE while the team works, one message per step, named by step kind. |
| `GET /approvals` | Payment and purchase requests with their status: pending by default, or `?status=paid`, `rejected`, `all`. |
| `POST /approvals/{id}/approve` | The human approves one request: cash leaves `cash_accounts`, a `payments` row is written, the invoice is marked paid or the lease's next due date moves, and the ticket resolves once nothing is pending on it. |
| `POST /approvals/{id}/reject` | The human declines one request. Nothing moves except the request's status. |
| `GET /cash` | Checking balance, the total already waiting on approval, and what is left after it. |
| `POST /reset` | Copies `data/campus_customs.db` over the working copy: tickets open again, balance back to $3,400.00, workflow tables empty. |

### What the routes enforce

- **One job at a time.** A second run, or a reset during a run, is refused with 409 rather than queued, so a
  browser that gives up can never leave a run to start on its own later.
- **Only open tickets run.** A missing ticket is 404 and an already-closed one is 409, before any model is called.
- **A refusal stays a refusal.** When an MCP tool refuses, the route returns 409 with the tool's own reason
  (and 404 when a row does not exist), so the board shows the shop's rule, not a generic error.
- **The approve route is the only way cash moves.** It calls `pay_approved_request`, the one tool no agent can see.
- **Human decisions are audited too.** Each approve or reject is appended to `output/audit_trail.json` and pushed
  to the live feed as an entry by `Human`, including the ones that were refused.
- **Reset never erases history.** It restores the database only; `output/audit_trail.json` stays append-only, and
  just the in-memory feed is cleared.
- **The dashboard can reach it.** CORS is open to the Vite dev server (`localhost:5173`) and nothing else.

## Dashboard

`frontend/` is a React + Vite + TypeScript app — the desk a person actually sits at. It talks to the
backend on port 8000 and holds no copy of the shop's rules: every figure it shows came from a route
that got it from an MCP tool. Its look and layout decisions are written up in `output/design.md`.

```bash
cd frontend && npm install && npm run dev     # http://localhost:5173
```

The backend must be running first; CORS is open to `localhost:5173` and nothing else.

| Part of the screen | What it does | Routes it uses |
|---|---|---|
| Header | Shop date, live-connection dot, checking balance with the amount already promised, reset button | `GET /cash`, `POST /reset` |
| Desk tickets (left) | The three tickets and their status; the selected one expands to show the request in the requester's words, the item, the linked invoice or lease, any payment request, any saved draft, and the Boss's outcome | `GET /tickets`, `GET /tickets/{id}` |
| Run the team | Runs the selected ticket; disabled while the board is busy or once the ticket is closed | `POST /tickets/{id}/run` |
| Agent activity (centre) | Every model turn, tool call, hand-off, refusal and report as it happens, indented by delegation depth, ending in a totals strip | `GET /events`, `GET /events/stream` |
| The team (right) | One card per agent: idle, working or reported, with its turn and tool counts, its delegation chain and its summary | derived from the event stream |
| Needs a human (right) | Each pending payment with its amount, payee, reason and who prepared it, plus approve and decline | `GET /approvals`, `POST /approvals/{id}/approve`, `POST /approvals/{id}/reject` |

### What the dashboard enforces

- **Approve is disabled until a human types their name**, matching the tool that refuses an approver
  named after an agent. Decline sits next to it at the same size.
- **Tickets are marked resolved because the database says so**, not because a run finished: the board
  re-reads `/tickets` after every run and every decision.
- **The human's approve and reject appear in the activity stream** as their own rows, so the record on
  screen matches `output/audit_trail.json`.
- **No polling.** The board refreshes only when an agent prepares a payment and when a run ends, both
  learned from the event stream.

## The live run

All three tickets worked end to end on the dashboard against a freshly reset database. The full record is in
[`resolved_tickets.json`](resolved_tickets.json), the screens are in [`resolved_board.html`](resolved_board.html),
the plan it is measured against is in [`desk_tickets.html`](desk_tickets.html), and every step is appended to
[`audit_trail.json`](audit_trail.json).

| | 101 Bulldog tee | 102 Rent due | 103 Bulk hoodie discount |
|---|---|---|---|
| Boss called first | Inventory | Facilities | Inventory |
| Hand-offs | 3 | 2 | 3 |
| Chain | Boss → each specialist | Boss → Facilities → Accounting | Boss → each specialist |
| Model turns | 14 | 9 | 11 |
| Tool calls | 14 | 8 | 14 |
| Tokens | 38,812 | 22,411 | 30,648 |
| Agent time | 7.7s | 26.4s | 34.8s |
| Payment requested | $840.00 invoice 501 | $2,400.00 September rent | none — unaffordable |
| Human decision | approved | approved | not needed |
| Draft saved | 1, to Tauhid Zaman | none needed | 1, to the Yale AI Club |
| Final status | resolved | resolved | resolved |
| Checking after | $2,560.00 | $160.00 | $160.00 |

**Across the three runs:** 34 model requests, 36 tool calls, 8 delegations, 91,871 tokens, 69 seconds of agent
time, 108 new audit entries. No errors, no refusals, no retries.

### Cash

$3,400.00 − $840.00 (invoice 501) − $2,400.00 (September rent) = **$160.00**, which matches
`cash_accounts.checking` and the two rows in `payments`. No money comes into this shop, so the opening balance
was a hard ceiling on all three tickets.

Order mattered: paying invoice 501 first unblocked the only apparel vendor, and paying rent second protected a
fixed obligation. Had ticket 103 run before 102, the $264.00 hoodie restock would have been affordable out of
$2,560.00 — and the shop would then have been $104.00 short of its rent.

### What the run showed about the design

- **The two-step payment held.** Agents filed two requests and moved no money. Both payments left checking only
  after a person typed their name on the board, and both are in `payments` with that name against them.
- **The cash ceiling was respected without the guardrail firing.** Accounting read the $160.00 balance, worked
  out that a $264.00 restock was $104.00 short, and never called `request_purchase_order`. The tool would have
  refused it; the agent stopped first. Across the run, zero tool calls were refused.
- **Agents re-read the database instead of trusting hand-offs.** Accounting pulled invoice 501 itself rather
  than taking the amount from Inventory's report; the Boss checked the balance before each final call.
- **Nothing was sent, and one draft needed the human.** Both drafts describe 2026-09-05 as the earliest
  *possible* date and neither names a figure. But draft 1 tells Tauhid that "the vendor's invoice block must
  be cleared before an order can be placed" — an unpaid invoice disclosed to a customer, which the Customer
  Service prompt explicitly forbids. `save_message_draft` stores text without reading it, so nothing in code
  caught it; only the drafts-never-send rule and a human reviewer stand in the way. This is the one guardrail
  the run actually leaked through.
- **A ticket with nothing pending resolves straight away.** Ticket 103 went from `open` to `resolved` without
  passing through `awaiting_approval`, because no human decision was outstanding.

### Where the live run differed from the plan

- **Ticket 101:** Inventory never called `list_vendors` — `get_vendor_invoice` already returned the vendor, its
  lead time and the blocked flag. Accounting called it later instead.
- **Ticket 102:** matched the plan exactly, including the three-deep Facilities → Accounting hop.
- **Ticket 103:** the plan expected `request_purchase_order` to fire and be refused. It was never attempted.
  Accounting also quoted the discount on all 20 units, though the Boss and the draft narrowed the actual offer
  to the 8 on the shelf.

### Still open at $160.00

- Tauhid's size S tee needs an $8.00 purchase order to Bulldog Print Co, now unblocked and affordable. The Boss
  left it as a follow-up rather than filing it.
- The Yale AI Club's remaining 12 hoodies need $264.00.
- October rent of $2,400.00 is due 2026-10-02, which the shop cannot currently pay.

## Safety

### Guardrails for real customers and real money

- **A human approves every payment.** Agents can only create *pending* requests. The tool that moves cash (`pay_approved_request`) isn't in any agent's toolset; only the backend's human approval route calls it. It also refuses approvers named after an agent.
- **No negative balances.** Request tools refuse amounts checking can't cover and warn when pending requests would overdraw it. The pay step checks the balance again inside a locked transaction and refuses if the money isn't there.
- **No invented money.** Payment amounts come from the invoice, the lease, or qty × `unit_cost`. Agents never type a dollar figure into a payment tool.
- **No double payments.** Duplicate pending requests are refused. Paid invoices can't be paid again. Closed tickets can't be re-run.
- **Shop rules are enforced in code, not just in prompts.** Purchase orders to a vendor with an open invoice are refused. Quotes below unit cost are refused.
- **Least privilege.** Each agent sees only the tools its job needs. Only Accounting can prepare payments, and only Customer Service can save drafts.
- **Honest attribution.** `requested_by` and `drafted_by` are filled in from the agent that actually made the call, so an agent can't sign as someone else.
- **Nothing leaves the shop.** There are no email, phone or vendor tools. Customer messages are drafts on the board, recipients are always the ticket's requester, and Customer Service is told never to share cash, margins or vendor problems.
- **No made-up facts.** Tools return `found: false` instead of guessing. Every prompt requires numbers to come from tools.
- **Every step is auditable.** The append-only audit trail records who did what, with which arguments and results.
- **Resettable.** The original `campus_customs.db` is never written to.

### Limits that keep token use in check

- **One model, cheap settings:** `gpt-6-luna` with low reasoning effort, and at most 4,000 output tokens per response.
- **Per-ticket budget, shared by every agent on the ticket:** 40 model requests, 60 tool calls, 250,000 total tokens. Delegated runs count toward the caller's budget, and the run stops cleanly with an `error` event if the budget is hit.
- **Delegation caps:** chain depth 3, at most 8 hand-offs per ticket, no self- or back-delegation.
- **Lean context:** each agent sees only its own tools. Delegated agents start fresh with a focused task instead of the whole conversation, and tool results stored in the audit trail are capped at 4,000 characters.
- **Fail fast:** 60-second request timeout, at most 2 transient retries per call, and 2 output/tool-argument retries per agent.
- **Measured on the full live run:** 14, 9 and 11 model requests per ticket and 38.8k, 22.4k and 30.6k
  tokens — the heaviest ticket used about a third of the 40-request budget and an eighth of the 250k token
  budget. No run came close to a limit.
