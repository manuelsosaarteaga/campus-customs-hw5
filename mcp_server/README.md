# Campus Customs MCP Server

A [FastMCP](https://gofastmcp.com) server that gives the Campus Customs agent team (Boss, Inventory, Accounting, Facilities, Customer Service) access to the shop's data. Every agent reads and changes shop data through these tools, never by querying the database directly.

## Database

The server uses the working copy **`data/campus_customs_new.db`**, found relative to `server.py`. It never touches the original `data/campus_customs.db`, which is kept for resets.

- Tools only return what's in the database. If a row doesn't exist, the tool returns `"found": false` with a message instead of a made-up value.
- Money amounts are always computed from the database (invoice, lease, or qty × unit cost) and never taken from the caller.
- Overdue and due-soon checks use the shop's date in `desk.date_today`, not the real clock.
- Read tools use a query-only connection. Write tools run in a single transaction.
- The server adds three workflow tables to the working copy if they're missing: `approval_requests`, `message_drafts` and `ticket_outcomes`. Resetting to the original database removes them, and they come back empty.

## How payments work

Paying takes two steps, so cash never moves without a human:

1. **An agent prepares a request.** Accounting calls `request_invoice_payment`, `request_rent_payment` or `request_purchase_order`. This adds a *pending* row to `approval_requests` and reports the cash picture. Nothing is paid.
2. **A human approves it.** The backend's approve route calls `pay_approved_request` with the approver's name. Only this tool moves cash: it lowers `cash_accounts.balance`, writes a `payments` row, and marks the invoice paid or moves the lease's `next_due` forward a month. It refuses if checking can't cover the payment (no negative balances).

`close_ticket`, `pay_approved_request` and `reject_approval_request` are for the backend only. The agent team's tool lists leave them out.

## Tools

### Read

| Tool | Arguments | Reads | Returns |
|---|---|---|---|
| `check_stock_and_price` | `sku`, `size`, optional `qty_needed` | `inventory`, `pricing` | Units on hand and their location, other sizes, unit cost, list price, margin per unit, and whether stock covers `qty_needed` (with the shortfall) |
| `get_vendor_invoice` | `invoice_id` | `invoices`, `vendors`, `desk` | Amount, due date, status, days overdue, the vendor and its lead time, and whether the vendor is blocked from shipping |
| `get_lease` | `lease_id` | `leases`, `desk` | Space, landlord, monthly rent, next due date, days until due, overdue or not |
| `get_ticket` | `ticket_id` | `tickets`, `desk`, workflow tables | The ticket plus its payment requests, drafts and outcome so far |
| `list_tickets` | optional `status` | `tickets` | Every ticket with its status (`open`, `awaiting_approval`, `resolved`) |
| `get_cash_balance` | none | `cash_accounts`, `approval_requests` | Checking balance, total waiting on approval, what's left after pending |
| `list_vendors` | none | `vendors`, `invoices`, `desk` | Specialty, lead time, open invoices, blocked flag, earliest delivery if ordered today |
| `list_open_invoices` | none | `invoices`, `vendors`, `desk` | Every unpaid invoice with days overdue |
| `quote_bulk_price` | `sku`, `qty`, `discount_pct` | `pricing` | Discounted unit price, order total, margin, break-even discount. Refuses below-cost prices |
| `list_approval_requests` | optional `status`, `ticket_id` | `approval_requests` | Payment and purchase requests and their status |
| `list_message_drafts` | optional `ticket_id` | `message_drafts` | Drafts saved on the board |
| `list_payments` | none | `payments` | The ledger of approved payments and the total paid |

### Agent write tools (prepare work, never move cash)

| Tool | Arguments | Effect |
|---|---|---|
| `request_invoice_payment` | `invoice_id`, `ticket_id`, `reason`, `requested_by` | Pending request to pay an open invoice in full. Refuses duplicates or amounts checking can't cover |
| `request_rent_payment` | `lease_id`, `ticket_id`, `reason`, `requested_by` | Pending request for one month's rent. Refuses duplicates or amounts checking can't cover |
| `request_purchase_order` | `vendor_id`, `sku`, `size`, `qty`, `ticket_id`, `reason`, `requested_by` | Pending restock purchase at qty × unit cost. Refuses a vendor with an open invoice, unknown items, or amounts checking can't cover |
| `save_message_draft` | `ticket_id`, `subject`, `body`, `drafted_by` | Saves a draft to the ticket's requester. Nothing is sent |

### Backend-only tools

| Tool | Arguments | Effect |
|---|---|---|
| `close_ticket` | `ticket_id`, `outcome`, `decided_by` | Records the Boss's outcome. Status becomes `awaiting_approval` if requests are pending, otherwise `resolved` |
| `pay_approved_request` | `request_id`, `approved_by` | **Human approval only.** Moves the cash and updates the bill. Refuses insufficient cash or an agent as approver |
| `reject_approval_request` | `request_id`, `decided_by`, optional `note` | **Human approval only.** Declines a request. No cash moves |

## Running it

From the project root, with the project's virtual environment:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python mcp_server/server.py
```

This starts the server over stdio. Claude Code connects to it through `.mcp.json`. The agent backend starts its own copy automatically (`backend/mcp_tools.py`), so you never need to run it by hand for the agents.
