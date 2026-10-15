"""Campus Customs MCP server.

Gives the agent team access to the shop's data in data/campus_customs_new.db.
Every value a tool returns comes from the database. If a row isn't there, the
tool says so instead of guessing. Money amounts are always computed from the
database, never taken from the caller.

Payments are two steps. Agents can only *request* a payment (request_* tools),
which adds a pending row to approval_requests. Cash moves only when a human
approves it through pay_approved_request, which the backend calls from its
approve route and never gives to an agent.
"""

import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastmcp import FastMCP

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "campus_customs_new.db"
AGENT_NAMES = {"boss", "inventory", "accounting", "facilities", "customer service"}
MAX_DRAFT_CHARS = 2000

mcp = FastMCP("campus-customs")

# Workflow tables the server adds to the working copy. They hold the agents' work
# (payment requests waiting for a human, message drafts, ticket outcomes), not shop
# facts. Resetting to the original database removes them; they come back empty.
WORKFLOW_SCHEMA = """
CREATE TABLE IF NOT EXISTS approval_requests (
    id INTEGER PRIMARY KEY,
    ticket_id INTEGER NOT NULL,
    kind TEXT NOT NULL,                -- invoice | rent | purchase_order
    ref_id INTEGER,                    -- invoices.id or leases.id; NULL for purchase_order
    vendor_id INTEGER,
    sku TEXT,
    size TEXT,
    qty INTEGER,
    payee TEXT NOT NULL,
    amount REAL NOT NULL,
    reason TEXT NOT NULL,
    requested_by TEXT NOT NULL,
    status TEXT NOT NULL,              -- pending | paid | rejected
    created_at TEXT NOT NULL,
    expected_arrival TEXT,
    decided_by TEXT,
    decided_at TEXT,
    decision_note TEXT,
    payment_id INTEGER
);
CREATE TABLE IF NOT EXISTS message_drafts (
    id INTEGER PRIMARY KEY,
    ticket_id INTEGER NOT NULL,
    recipient TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    drafted_by TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ticket_outcomes (
    ticket_id INTEGER PRIMARY KEY,
    outcome TEXT NOT NULL,
    decided_by TEXT NOT NULL,
    closed_at TEXT NOT NULL
);
"""


@contextmanager
def _db(write: bool = False):
    """Open the working database. Reads use a query-only connection; writes run in one transaction."""
    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"Working database not found at {DB_PATH}. "
            "Copy data/campus_customs.db to data/campus_customs_new.db first."
        )
    # mode=rw never creates a file, so a missing database can't silently become an empty one.
    conn = sqlite3.connect(f"{DB_PATH.as_uri()}?mode=rw", uri=True, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(WORKFLOW_SCHEMA)
        if not write:
            conn.execute("PRAGMA query_only = ON")
            yield conn
            return
        conn.execute("BEGIN IMMEDIATE")  # take the write lock before reading balances
        try:
            yield conn
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()


def _shop_today(conn: sqlite3.Connection) -> date:
    """The shop's "today" comes from desk.date_today, not the real clock."""
    return date.fromisoformat(conn.execute("SELECT date_today FROM desk").fetchone()["date_today"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _add_month(d: date) -> date:
    year, month = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    for day in (d.day, 30, 29, 28):  # clamp e.g. Jan 31 -> Feb 28
        try:
            return date(year, month, day)
        except ValueError:
            continue
    raise ValueError(f"Can't add a month to {d}")


def _refuse(reason: str, **extra) -> dict:
    return {"ok": False, "refused": True, "reason": reason, **extra}


def _ticket(conn: sqlite3.Connection, ticket_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()


def _checking(conn: sqlite3.Connection) -> sqlite3.Row:
    return conn.execute("SELECT name, balance, date FROM cash_accounts WHERE name = 'checking'").fetchone()


def _pending_total(conn: sqlite3.Connection) -> float:
    total = conn.execute("SELECT COALESCE(SUM(amount), 0) FROM approval_requests WHERE status = 'pending'").fetchone()[0]
    return round(total, 2)


def _open_invoices_for(conn: sqlite3.Connection, vendor_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT id, amount, due_date FROM invoices WHERE vendor_id = ? AND status = 'open' ORDER BY id", (vendor_id,)
    ).fetchall()


def _duplicate_request(conn: sqlite3.Connection, kind: str, ref_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT id, status FROM approval_requests WHERE kind = ? AND ref_id = ? AND status = 'pending'",
        (kind, ref_id),
    ).fetchone()


def _cash_check(conn: sqlite3.Connection, amount: float) -> dict:
    """Balance facts every payment request reports, so the human sees the cash picture before approving."""
    balance = _checking(conn)["balance"]
    pending = _pending_total(conn)
    info = {
        "checking_balance": balance,
        "already_pending": pending,
        "balance_after_this_and_pending": round(balance - pending - amount, 2),
    }
    if amount > balance - pending:
        info["warning"] = (
            "Approving this plus the requests already pending would overdraw checking. "
            "The pay step will refuse whichever payment no longer fits."
        )
    return info


def _create_request(conn: sqlite3.Connection, **fields) -> int:
    fields.update(status="pending", created_at=_now())
    cols = ", ".join(fields)
    marks = ", ".join("?" for _ in fields)
    return conn.execute(f"INSERT INTO approval_requests ({cols}) VALUES ({marks})", tuple(fields.values())).lastrowid


def _settle_ticket_if_done(conn: sqlite3.Connection, ticket_id: int) -> str | None:
    """A ticket waiting on approvals becomes resolved once a human has decided all of them."""
    t = _ticket(conn, ticket_id)
    if t is None:
        return None
    left = conn.execute(
        "SELECT COUNT(*) FROM approval_requests WHERE ticket_id = ? AND status = 'pending'", (ticket_id,)
    ).fetchone()[0]
    if t["status"] == "awaiting_approval" and left == 0:
        conn.execute("UPDATE tickets SET status = 'resolved' WHERE id = ?", (ticket_id,))
        return "resolved"
    return t["status"]


def _request_row(r: sqlite3.Row) -> dict:
    return {k: r[k] for k in r.keys() if r[k] is not None}


# ---------------------------------------------------------------------------
# Read tools
# ---------------------------------------------------------------------------


@mcp.tool
def check_stock_and_price(sku: str, size: str, qty_needed: int | None = None) -> dict:
    """Check units on hand for one product size, plus its unit cost and list price.

    Pass qty_needed to see whether stock covers a request and how many units are short.
    Also lists what's on hand in the product's other sizes. Use this for customer orders
    and bulk or discount requests.
    """
    sku, size = sku.strip().upper(), size.strip().upper()
    with _db() as conn:
        item = conn.execute(
            "SELECT sku, name, size, qty, location FROM inventory WHERE sku = ? AND size = ?",
            (sku, size),
        ).fetchone()
        other_sizes = conn.execute(
            "SELECT size, qty FROM inventory WHERE sku = ? AND size != ? ORDER BY rowid",
            (sku, size),
        ).fetchall()
        price = conn.execute(
            "SELECT unit_cost, list_price FROM pricing WHERE sku = ?", (sku,)
        ).fetchone()

    if item is None:
        return {
            "found": False,
            "sku": sku,
            "size": size,
            "message": f"No inventory row for {sku} in size {size}.",
            "sizes_on_file": [row["size"] for row in other_sizes],
        }

    result = {
        "found": True,
        "sku": item["sku"],
        "name": item["name"],
        "size": item["size"],
        "on_hand": item["qty"],
        "location": item["location"],
        "other_sizes_on_hand": {row["size"]: row["qty"] for row in other_sizes},
        "unit_cost": price["unit_cost"] if price else None,
        "list_price": price["list_price"] if price else None,
        "margin_per_unit_at_list": round(price["list_price"] - price["unit_cost"], 2) if price else None,
    }
    if price is None:
        result["pricing_note"] = f"No pricing row for {sku}."
    if qty_needed is not None:
        result["qty_needed"] = qty_needed
        result["can_fill_from_stock"] = item["qty"] >= qty_needed
        result["shortfall"] = max(qty_needed - item["qty"], 0)
    return result


@mcp.tool
def get_vendor_invoice(invoice_id: int) -> dict:
    """Look up a vendor invoice, the vendor it's owed to, and whether it's overdue.

    Overdue is measured against the shop's today (desk.date_today). A vendor won't ship
    new product while it has any open invoice, so this also lists all of the vendor's
    open invoices and whether a restock from them is blocked.
    """
    with _db() as conn:
        today = _shop_today(conn)
        inv = conn.execute(
            """
            SELECT i.id, i.vendor_id, i.amount, i.due_date, i.status, i.description,
                   v.name AS vendor_name, v.specialty, v.lead_days
            FROM invoices i
            LEFT JOIN vendors v ON v.id = i.vendor_id
            WHERE i.id = ?
            """,
            (invoice_id,),
        ).fetchone()
        if inv is None:
            return {"found": False, "invoice_id": invoice_id, "message": f"No invoice with id {invoice_id}."}
        open_invoices = conn.execute(
            "SELECT id, amount FROM invoices WHERE vendor_id = ? AND status = 'open' ORDER BY id",
            (inv["vendor_id"],),
        ).fetchall()

    is_open = inv["status"] == "open"
    days_past_due = (today - date.fromisoformat(inv["due_date"])).days
    result = {
        "found": True,
        "shop_today": today.isoformat(),
        "invoice_id": inv["id"],
        "amount": inv["amount"],
        "due_date": inv["due_date"],
        "status": inv["status"],
        "description": inv["description"],
        "is_overdue": is_open and days_past_due > 0,
        "days_overdue": max(days_past_due, 0) if is_open else 0,
        "vendor": None,
        "vendor_open_invoices": [{"invoice_id": r["id"], "amount": r["amount"]} for r in open_invoices],
        "vendor_blocked_from_shipping": len(open_invoices) > 0,
    }
    if inv["vendor_name"] is not None:
        result["vendor"] = {
            "id": inv["vendor_id"],
            "name": inv["vendor_name"],
            "specialty": inv["specialty"],
            "lead_days": inv["lead_days"],
            "earliest_delivery_if_ordered_today": (today + timedelta(days=inv["lead_days"])).isoformat(),
        }
    return result


@mcp.tool
def get_lease(lease_id: int) -> dict:
    """Look up a shop lease: the space, landlord, monthly rent, and next due date.

    Days until due are counted from the shop's today (desk.date_today). Use this to
    check a rent notice before anyone prepares a payment.
    """
    with _db() as conn:
        today = _shop_today(conn)
        lease = conn.execute(
            "SELECT id, space_name, landlord, monthly_rent, next_due, notes FROM leases WHERE id = ?",
            (lease_id,),
        ).fetchone()

    if lease is None:
        return {"found": False, "lease_id": lease_id, "message": f"No lease with id {lease_id}."}

    days_until_due = (date.fromisoformat(lease["next_due"]) - today).days
    return {
        "found": True,
        "shop_today": today.isoformat(),
        "lease_id": lease["id"],
        "space_name": lease["space_name"],
        "landlord": lease["landlord"],
        "monthly_rent": lease["monthly_rent"],
        "next_due": lease["next_due"],
        "days_until_due": days_until_due,
        "is_overdue": days_until_due < 0,
        "notes": lease["notes"],
    }


@mcp.tool
def get_ticket(ticket_id: int) -> dict:
    """Read one desk ticket with everything already attached to it.

    Returns the ticket's fields (type, requester, sku/size/qty, linked lease_id or
    invoice_id, status, notes), the shop's today, and any payment requests, message
    drafts, or final outcome recorded for it so far.
    """
    with _db() as conn:
        t = _ticket(conn, ticket_id)
        if t is None:
            return {"found": False, "ticket_id": ticket_id, "message": f"No ticket with id {ticket_id}."}
        requests = conn.execute(
            "SELECT id, kind, payee, amount, status, requested_by FROM approval_requests WHERE ticket_id = ? ORDER BY id",
            (ticket_id,),
        ).fetchall()
        drafts = conn.execute(
            "SELECT id, subject, drafted_by FROM message_drafts WHERE ticket_id = ? ORDER BY id", (ticket_id,)
        ).fetchall()
        outcome = conn.execute("SELECT * FROM ticket_outcomes WHERE ticket_id = ?", (ticket_id,)).fetchone()
        today = _shop_today(conn)
    return {
        "found": True,
        "shop_today": today.isoformat(),
        "ticket": {k: t[k] for k in t.keys()},
        "approval_requests": [dict(r) for r in requests],
        "message_drafts": [dict(d) for d in drafts],
        "outcome": dict(outcome) if outcome else None,
    }


@mcp.tool
def list_tickets(status: str | None = None) -> dict:
    """List desk tickets (id, type, requester, subject, status), optionally only one status.

    Status is open, awaiting_approval (closed by the team but a payment still needs a
    human), or resolved.
    """
    with _db() as conn:
        sql = "SELECT id, type, requester, subject, status, created_at FROM tickets"
        rows = conn.execute(sql + " WHERE status = ? ORDER BY id" if status else sql + " ORDER BY id",
                            (status,) if status else ()).fetchall()
    return {"tickets": [dict(r) for r in rows], "count": len(rows)}


@mcp.tool
def get_cash_balance() -> dict:
    """Current checking balance, plus the total of payment requests still waiting for a human.

    Cash only goes out in this shop (no revenue is recorded), so this is the ceiling on
    everything the team can pay for.
    """
    with _db() as conn:
        checking = _checking(conn)
        pending = _pending_total(conn)
        today = _shop_today(conn)
    return {
        "shop_today": today.isoformat(),
        "account": checking["name"],
        "balance": checking["balance"],
        "as_of": checking["date"],
        "pending_approval_total": pending,
        "available_after_pending": round(checking["balance"] - pending, 2),
    }


@mcp.tool
def list_vendors() -> dict:
    """All vendors with what they supply, lead time, and whether they're blocked from shipping.

    A vendor with any open (unpaid) invoice won't ship new product until it's paid.
    earliest_delivery_if_ordered_today = shop today + lead_days.
    """
    with _db() as conn:
        today = _shop_today(conn)
        vendors = conn.execute("SELECT id, name, specialty, lead_days FROM vendors ORDER BY id").fetchall()
        result = []
        for v in vendors:
            open_inv = _open_invoices_for(conn, v["id"])
            result.append({
                **dict(v),
                "open_invoices": [{"invoice_id": i["id"], "amount": i["amount"], "due_date": i["due_date"]} for i in open_inv],
                "blocked_from_shipping": bool(open_inv),
                "earliest_delivery_if_ordered_today": (today + timedelta(days=v["lead_days"])).isoformat(),
            })
    return {"shop_today": today.isoformat(), "vendors": result}


@mcp.tool
def list_open_invoices() -> dict:
    """All unpaid vendor invoices with vendor name, amount, due date, and days overdue (vs. shop today)."""
    with _db() as conn:
        today = _shop_today(conn)
        rows = conn.execute(
            """
            SELECT i.id, i.vendor_id, v.name AS vendor_name, i.amount, i.due_date, i.description
            FROM invoices i LEFT JOIN vendors v ON v.id = i.vendor_id
            WHERE i.status = 'open' ORDER BY i.due_date
            """
        ).fetchall()
    invoices = []
    for r in rows:
        late = (today - date.fromisoformat(r["due_date"])).days
        invoices.append({**dict(r), "is_overdue": late > 0, "days_overdue": max(late, 0)})
    return {
        "shop_today": today.isoformat(),
        "open_invoices": invoices,
        "total_open": round(sum(i["amount"] for i in invoices), 2),
    }


@mcp.tool
def quote_bulk_price(sku: str, qty: int, discount_pct: float) -> dict:
    """Price a bulk or discounted order from the pricing table, before anyone promises it.

    Returns the discounted unit price, order total, margin per unit and overall, and the
    break-even discount (where price would equal unit cost). Refuses quotes below cost.
    """
    sku = sku.strip().upper()
    if qty <= 0:
        return _refuse("qty must be at least 1.")
    if not 0 <= discount_pct < 100:
        return _refuse("discount_pct must be between 0 and 100.")
    with _db() as conn:
        price = conn.execute("SELECT unit_cost, list_price FROM pricing WHERE sku = ?", (sku,)).fetchone()
    if price is None:
        return {"found": False, "sku": sku, "message": f"No pricing row for {sku}."}

    cost, list_price = price["unit_cost"], price["list_price"]
    unit = round(list_price * (1 - discount_pct / 100), 2)
    quote = {
        "found": True,
        "sku": sku,
        "qty": qty,
        "list_price": list_price,
        "unit_cost": cost,
        "discount_pct": discount_pct,
        "discounted_unit_price": unit,
        "order_total": round(unit * qty, 2),
        "order_total_at_list": round(list_price * qty, 2),
        "discount_given": round((list_price - unit) * qty, 2),
        "margin_per_unit": round(unit - cost, 2),
        "margin_pct": round((unit - cost) / unit * 100, 1) if unit else None,
        "order_margin": round((unit - cost) * qty, 2),
        "break_even_discount_pct": round((list_price - cost) / list_price * 100, 1),
    }
    if unit < cost:
        return _refuse(f"A {discount_pct}% discount prices {sku} at ${unit:.2f}, below the ${cost:.2f} unit cost.", quote=quote)
    return {"ok": True, **quote}


@mcp.tool
def list_approval_requests(status: str | None = "pending", ticket_id: int | None = None) -> dict:
    """Payment and purchase requests waiting for (or already given) a human decision.

    status: pending (default), paid, rejected, or None for all. Optionally filter to one ticket.
    """
    clauses, params = [], []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if ticket_id is not None:
        clauses.append("ticket_id = ?")
        params.append(ticket_id)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    with _db() as conn:
        rows = conn.execute(f"SELECT * FROM approval_requests{where} ORDER BY id", params).fetchall()
    return {"requests": [_request_row(r) for r in rows], "count": len(rows)}


@mcp.tool
def list_message_drafts(ticket_id: int | None = None) -> dict:
    """Message drafts saved on the board (never sent), optionally for one ticket."""
    with _db() as conn:
        sql = "SELECT * FROM message_drafts"
        rows = conn.execute(sql + " WHERE ticket_id = ? ORDER BY id" if ticket_id is not None else sql + " ORDER BY id",
                            (ticket_id,) if ticket_id is not None else ()).fetchall()
    return {"drafts": [dict(r) for r in rows], "count": len(rows)}


@mcp.tool
def list_payments() -> dict:
    """The payments ledger: every human-approved payment that has left checking."""
    with _db() as conn:
        rows = conn.execute("SELECT * FROM payments ORDER BY id").fetchall()
    payments = [dict(r) for r in rows]
    return {"payments": payments, "total_paid": round(sum(p["amount"] for p in payments), 2)}


# ---------------------------------------------------------------------------
# Agent write tools: prepare work for a human, never move cash
# ---------------------------------------------------------------------------


@mcp.tool
def request_invoice_payment(invoice_id: int, ticket_id: int, reason: str, requested_by: str) -> dict:
    """Ask a human to approve paying a vendor invoice in full. Does NOT pay it.

    The amount and payee come from the invoice itself. Adds a pending approval request and
    reports the cash picture. Refuses if the invoice isn't open, a request for it is already
    pending, or checking can't cover it.
    """
    with _db(write=True) as conn:
        if _ticket(conn, ticket_id) is None:
            return _refuse(f"No ticket with id {ticket_id}.")
        inv = conn.execute(
            "SELECT i.*, v.name AS vendor_name FROM invoices i LEFT JOIN vendors v ON v.id = i.vendor_id WHERE i.id = ?",
            (invoice_id,),
        ).fetchone()
        if inv is None:
            return _refuse(f"No invoice with id {invoice_id}.")
        if inv["status"] != "open":
            return _refuse(f"Invoice {invoice_id} is {inv['status']}, not open; nothing to pay.")
        if dup := _duplicate_request(conn, "invoice", invoice_id):
            return _refuse(f"Request {dup['id']} to pay invoice {invoice_id} is already pending.", request_id=dup["id"])
        if inv["amount"] > _checking(conn)["balance"]:
            return _refuse(f"Checking has ${_checking(conn)['balance']:.2f}; invoice {invoice_id} is ${inv['amount']:.2f}.")
        cash = _cash_check(conn, inv["amount"])
        request_id = _create_request(
            conn, ticket_id=ticket_id, kind="invoice", ref_id=invoice_id, vendor_id=inv["vendor_id"],
            payee=inv["vendor_name"] or f"vendor {inv['vendor_id']}", amount=inv["amount"],
            reason=reason, requested_by=requested_by,
        )
    return {"ok": True, "request_id": request_id, "status": "pending", "kind": "invoice", "invoice_id": invoice_id,
            "payee": inv["vendor_name"], "amount": inv["amount"], **cash,
            "next_step": "A human must approve this on the board before any cash moves."}


@mcp.tool
def request_rent_payment(lease_id: int, ticket_id: int, reason: str, requested_by: str) -> dict:
    """Ask a human to approve paying one month's rent on a lease. Does NOT pay it.

    The amount and landlord come from the lease. When approved, the lease's next_due moves
    forward one month. Refuses if a rent request for the lease is already pending or
    checking can't cover it.
    """
    with _db(write=True) as conn:
        if _ticket(conn, ticket_id) is None:
            return _refuse(f"No ticket with id {ticket_id}.")
        lease = conn.execute("SELECT * FROM leases WHERE id = ?", (lease_id,)).fetchone()
        if lease is None:
            return _refuse(f"No lease with id {lease_id}.")
        if dup := _duplicate_request(conn, "rent", lease_id):
            return _refuse(f"Request {dup['id']} to pay rent on lease {lease_id} is already pending.", request_id=dup["id"])
        rent = lease["monthly_rent"]
        if rent > _checking(conn)["balance"]:
            return _refuse(f"Checking has ${_checking(conn)['balance']:.2f}; rent is ${rent:.2f}.")
        cash = _cash_check(conn, rent)
        request_id = _create_request(
            conn, ticket_id=ticket_id, kind="rent", ref_id=lease_id, payee=lease["landlord"], amount=rent,
            reason=reason, requested_by=requested_by,
        )
    return {"ok": True, "request_id": request_id, "status": "pending", "kind": "rent", "lease_id": lease_id,
            "payee": lease["landlord"], "amount": rent, "rent_due": lease["next_due"], **cash,
            "next_step": "A human must approve this on the board before any cash moves."}


@mcp.tool
def request_purchase_order(vendor_id: int, sku: str, size: str, qty: int, ticket_id: int, reason: str,
                           requested_by: str) -> dict:
    """Ask a human to approve a restock purchase from a vendor. Does NOT buy anything.

    Cost is qty x the SKU's unit_cost from pricing. Refuses if the vendor has an open
    invoice (they won't ship), the SKU/size isn't stocked, or checking can't cover it.
    Expected arrival = shop today + the vendor's lead_days.
    """
    sku, size = sku.strip().upper(), size.strip().upper()
    if qty <= 0:
        return _refuse("qty must be at least 1.")
    with _db(write=True) as conn:
        if _ticket(conn, ticket_id) is None:
            return _refuse(f"No ticket with id {ticket_id}.")
        vendor = conn.execute("SELECT * FROM vendors WHERE id = ?", (vendor_id,)).fetchone()
        if vendor is None:
            return _refuse(f"No vendor with id {vendor_id}.")
        if open_inv := _open_invoices_for(conn, vendor_id):
            ids = ", ".join(str(i["id"]) for i in open_inv)
            return _refuse(f"{vendor['name']} has open invoice(s) {ids} and won't ship until they're paid.")
        if conn.execute("SELECT 1 FROM inventory WHERE sku = ? AND size = ?", (sku, size)).fetchone() is None:
            return _refuse(f"{sku} size {size} isn't a stocked item.")
        price = conn.execute("SELECT unit_cost FROM pricing WHERE sku = ?", (sku,)).fetchone()
        if price is None:
            return _refuse(f"No pricing row for {sku}, so the cost can't be computed.")
        cost = round(price["unit_cost"] * qty, 2)
        if cost > _checking(conn)["balance"]:
            return _refuse(f"Checking has ${_checking(conn)['balance']:.2f}; {qty} x {sku} {size} costs ${cost:.2f}.",
                           cost=cost, unit_cost=price["unit_cost"])
        cash = _cash_check(conn, cost)
        arrival = (_shop_today(conn) + timedelta(days=vendor["lead_days"])).isoformat()
        request_id = _create_request(
            conn, ticket_id=ticket_id, kind="purchase_order", vendor_id=vendor_id, sku=sku, size=size, qty=qty,
            payee=vendor["name"], amount=cost, reason=reason, requested_by=requested_by, expected_arrival=arrival,
        )
    return {"ok": True, "request_id": request_id, "status": "pending", "kind": "purchase_order", "payee": vendor["name"],
            "sku": sku, "size": size, "qty": qty, "unit_cost": price["unit_cost"], "amount": cost,
            "expected_arrival_if_approved_today": arrival, **cash,
            "next_step": "A human must approve this on the board before any cash moves."}


@mcp.tool
def save_message_draft(ticket_id: int, subject: str, body: str, drafted_by: str) -> dict:
    """Save a message to the ticket's requester as a draft on the board. Nothing is ever sent.

    The recipient is always the ticket's requester, taken from the ticket.
    """
    if not subject.strip() or not body.strip():
        return _refuse("subject and body can't be empty.")
    if len(body) > MAX_DRAFT_CHARS:
        return _refuse(f"body is {len(body)} characters; keep drafts under {MAX_DRAFT_CHARS}.")
    with _db(write=True) as conn:
        t = _ticket(conn, ticket_id)
        if t is None:
            return _refuse(f"No ticket with id {ticket_id}.")
        draft_id = conn.execute(
            "INSERT INTO message_drafts (ticket_id, recipient, subject, body, drafted_by, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (ticket_id, t["requester"], subject.strip(), body.strip(), drafted_by, _now()),
        ).lastrowid
    return {"ok": True, "draft_id": draft_id, "recipient": t["requester"], "status": "draft",
            "note": "Saved on the board only. Nothing was emailed or sent."}


# ---------------------------------------------------------------------------
# Backend-only tools: the orchestrator and the human approval route call these.
# No agent's toolset includes them.
# ---------------------------------------------------------------------------


@mcp.tool
def close_ticket(ticket_id: int, outcome: str, decided_by: str) -> dict:
    """Record the Boss's final outcome for a ticket and update its status.

    Status becomes awaiting_approval if the ticket still has pending payment requests,
    otherwise resolved.
    """
    with _db(write=True) as conn:
        if _ticket(conn, ticket_id) is None:
            return _refuse(f"No ticket with id {ticket_id}.")
        pending = conn.execute(
            "SELECT COUNT(*) FROM approval_requests WHERE ticket_id = ? AND status = 'pending'", (ticket_id,)
        ).fetchone()[0]
        status = "awaiting_approval" if pending else "resolved"
        conn.execute("UPDATE tickets SET status = ? WHERE id = ?", (status, ticket_id))
        conn.execute(
            "INSERT OR REPLACE INTO ticket_outcomes (ticket_id, outcome, decided_by, closed_at) VALUES (?, ?, ?, ?)",
            (ticket_id, outcome, decided_by, _now()),
        )
    return {"ok": True, "ticket_id": ticket_id, "status": status, "pending_approvals": pending}


@mcp.tool
def pay_approved_request(request_id: int, approved_by: str) -> dict:
    """HUMAN APPROVAL ONLY. Pay a pending request: move cash, write the payments row, update the bill.

    Refuses if the approver isn't a named human, the request isn't pending, the bill
    changed since it was requested, or checking can't cover it (no negative balances).
    """
    approver = approved_by.strip()
    if not approver or approver.lower() in AGENT_NAMES:
        return _refuse("approved_by must be the name of the human approving this payment.")
    with _db(write=True) as conn:
        req = conn.execute("SELECT * FROM approval_requests WHERE id = ?", (request_id,)).fetchone()
        if req is None:
            return _refuse(f"No approval request with id {request_id}.")
        if req["status"] != "pending":
            return _refuse(f"Request {request_id} is already {req['status']}.")

        if req["kind"] == "invoice":
            inv = conn.execute("SELECT status FROM invoices WHERE id = ?", (req["ref_id"],)).fetchone()
            if inv is None or inv["status"] != "open":
                return _refuse(f"Invoice {req['ref_id']} is no longer open.")
        elif req["kind"] == "purchase_order":
            if open_inv := _open_invoices_for(conn, req["vendor_id"]):
                ids = ", ".join(str(i["id"]) for i in open_inv)
                return _refuse(f"{req['payee']} now has open invoice(s) {ids} and won't ship. Pay those first.")

        checking = _checking(conn)
        if req["amount"] > checking["balance"]:
            return _refuse(
                f"Not enough cash: checking has ${checking['balance']:.2f}, this payment is ${req['amount']:.2f}. "
                "No payment was made.",
                checking_balance=checking["balance"], amount=req["amount"],
            )

        today = _shop_today(conn).isoformat()
        new_balance = round(checking["balance"] - req["amount"], 2)
        conn.execute("UPDATE cash_accounts SET balance = ?, date = ? WHERE name = 'checking'", (new_balance, today))
        ref_id = req["ref_id"] if req["kind"] != "purchase_order" else req["id"]
        payment_id = conn.execute(
            "INSERT INTO payments (kind, ref_id, amount, account, paid_at, approved_by) VALUES (?, ?, ?, 'checking', ?, ?)",
            (req["kind"], ref_id, req["amount"], today, approver),
        ).lastrowid

        effect = None
        if req["kind"] == "invoice":
            conn.execute("UPDATE invoices SET status = 'paid' WHERE id = ?", (req["ref_id"],))
            effect = f"Invoice {req['ref_id']} marked paid."
        elif req["kind"] == "rent":
            lease = conn.execute("SELECT next_due FROM leases WHERE id = ?", (req["ref_id"],)).fetchone()
            next_due = _add_month(date.fromisoformat(lease["next_due"])).isoformat()
            conn.execute("UPDATE leases SET next_due = ? WHERE id = ?", (next_due, req["ref_id"]))
            effect = f"Lease {req['ref_id']} next_due moved from {lease['next_due']} to {next_due}."
        else:
            effect = f"Purchase order placed with {req['payee']}; expected arrival {req['expected_arrival']}."

        conn.execute(
            "UPDATE approval_requests SET status = 'paid', decided_by = ?, decided_at = ?, payment_id = ? WHERE id = ?",
            (approver, _now(), payment_id, request_id),
        )
        ticket_status = _settle_ticket_if_done(conn, req["ticket_id"])
    return {"ok": True, "request_id": request_id, "payment_id": payment_id, "kind": req["kind"], "payee": req["payee"],
            "amount": req["amount"], "approved_by": approver, "balance_before": checking["balance"],
            "balance_after": new_balance, "effect": effect, "ticket_id": req["ticket_id"], "ticket_status": ticket_status}


@mcp.tool
def reject_approval_request(request_id: int, decided_by: str, note: str = "") -> dict:
    """HUMAN APPROVAL ONLY. Decline a pending payment request. No cash moves."""
    decider = decided_by.strip()
    if not decider or decider.lower() in AGENT_NAMES:
        return _refuse("decided_by must be the name of the human making the decision.")
    with _db(write=True) as conn:
        req = conn.execute("SELECT * FROM approval_requests WHERE id = ?", (request_id,)).fetchone()
        if req is None:
            return _refuse(f"No approval request with id {request_id}.")
        if req["status"] != "pending":
            return _refuse(f"Request {request_id} is already {req['status']}.")
        conn.execute(
            "UPDATE approval_requests SET status = 'rejected', decided_by = ?, decided_at = ?, decision_note = ? WHERE id = ?",
            (decider, _now(), note, request_id),
        )
        ticket_status = _settle_ticket_if_done(conn, req["ticket_id"])
    return {"ok": True, "request_id": request_id, "status": "rejected", "ticket_id": req["ticket_id"],
            "ticket_status": ticket_status}


if __name__ == "__main__":
    mcp.run(show_banner=False)
