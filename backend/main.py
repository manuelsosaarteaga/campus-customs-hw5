"""Campus Customs backend API: the service the dashboard talks to.

It does three things:

1. Shows the desk board — the tickets, the checking balance, and the payment
   requests waiting on a human. Every one of those reads goes through the MCP
   server, so the API has no second copy of the shop's rules.
2. Runs the agent team on one ticket and broadcasts every step of every agent's
   loop live, so the board can show the work as it happens.
3. Takes the human's decision on a payment. This is the only path in the whole
   project that moves cash, and it is a person, not an agent, who triggers it.

Boot it from this directory:

    uvicorn main:app --reload --port 8000
"""

import asyncio
import json
import shutil
import sys
import uuid
from collections import deque
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:  # so `uvicorn backend.main:app` from the project root works too
    sys.path.insert(0, str(BACKEND_DIR))

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from agents import run_ticket
from audit import AUDIT_PATH, append_audit_event, now_iso
from mcp_tools import shop_toolset
from models import AuditEvent, TicketRunResult

ORIGINAL_DB = PROJECT_ROOT / "data" / "campus_customs.db"
WORKING_DB = PROJECT_ROOT / "data" / "campus_customs_new.db"

FEED_LIMIT = 500  # agent steps kept in memory for /events; the full record is always in output/audit_trail.json
SSE_KEEPALIVE_S = 15
# The Vite dev server for the Problem 8 dashboard.
DEV_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:4173"]


# ---------------------------------------------------------------------------
# Live feed of agent steps
# ---------------------------------------------------------------------------


class EventFeed:
    """The recent agent steps, in memory, with a sequence number per step.

    `output/audit_trail.json` is still the record of what happened; this is just the
    fast, tail-shaped view the board polls or streams. Every entry keeps the fields the
    audit trail uses (agent, chain, event, tool, tool_calls, result, tokens) and adds
    `seq` so a client can ask for "everything after what I already have".
    """

    def __init__(self, limit: int = FEED_LIMIT) -> None:
        self._events: deque[dict[str, Any]] = deque(maxlen=limit)
        self._next_seq = 1
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()

    @property
    def last_seq(self) -> int:
        return self._next_seq - 1

    def publish(self, event: AuditEvent) -> None:
        """Called by the agent runner for every step. Fans the step out to live listeners."""
        record = {"seq": self._next_seq, **event.model_dump(mode="json", exclude_none=True)}
        self._next_seq += 1
        self._events.append(record)
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(record)
            except asyncio.QueueFull:  # a listener that stopped reading never blocks a run
                pass

    def recent(self, since: int = 0, limit: int = 100, ticket_id: int | None = None) -> list[dict[str, Any]]:
        events = [e for e in self._events if e["seq"] > since]
        if ticket_id is not None:
            events = [e for e in events if e.get("ticket_id") == ticket_id]
        return events[-limit:]

    def clear(self) -> None:
        """Drop the in-memory tail (used on reset). The audit trail file is never touched."""
        self._events.clear()

    @contextmanager
    def subscribe(self) -> Iterator[asyncio.Queue[dict[str, Any]]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1000)
        self._subscribers.add(queue)
        try:
            yield queue
        finally:
            self._subscribers.discard(queue)

    def seed_from_audit_file(self) -> int:
        """Fill the tail from output/audit_trail.json at boot, so a restart doesn't blank the board."""
        if not AUDIT_PATH.exists():
            return 0
        try:
            entries = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return 0  # a half-written trail is not worth failing a boot over
        for entry in entries[-FEED_LIMIT:]:
            self._events.append({"seq": self._next_seq, **entry})
            self._next_seq += 1
        return len(self._events)


feed = EventFeed()


class RunGate:
    """One job at a time on the board: a ticket run, or a reset.

    The per-ticket token budget and the payment guardrails both assume a single run
    against the board, and a reset must not land in the middle of one. This is a plain
    flag rather than an `asyncio.Lock` on purpose: a lock makes a second request *wait*
    its turn, and a browser that gives up after a slow request would still leave that
    run queued to start on its own later. Checking and claiming happen with no `await`
    in between, so on a single event loop the claim is atomic.
    """

    def __init__(self) -> None:
        self.busy_with: str | None = None

    @property
    def busy(self) -> bool:
        return self.busy_with is not None

    @contextmanager
    def claim(self, what: str) -> Iterator[None]:
        self.busy_with = what
        try:
            yield
        finally:
            self.busy_with = None


gate = RunGate()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    feed.seed_from_audit_file()
    async with shop_toolset():  # one MCP server process for the life of the API
        yield


app = FastAPI(
    title="Campus Customs Operations API",
    description="The desk board, the agent team, and the human approval step for Campus Customs.",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware, allow_origins=DEV_ORIGINS, allow_methods=["GET", "POST"], allow_headers=["*"]
)


async def call_tool(name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Every read and write goes through the MCP server, the same one the agents use."""
    return await shop_toolset().direct_call_tool(name, args or {})


def checked(result: dict[str, Any]) -> dict[str, Any]:
    """MCP tools refuse instead of raising. Turn a refusal into an HTTP error carrying the reason."""
    if result.get("found") is False:
        raise HTTPException(status_code=404, detail=result)
    if result.get("ok") is False:
        raise HTTPException(status_code=409, detail=result)
    return result


def record_human_decision(tool: str, args: dict[str, Any], result: dict[str, Any]) -> None:
    """Put the human's approve/reject in the same audit trail and live feed as the agents' steps."""
    event = AuditEvent(
        timestamp=now_iso(),
        run_id=f"human-{uuid.uuid4()}",
        ticket_id=result.get("ticket_id") or 0,  # 0 when the request was refused before a ticket was known
        agent="Human",
        chain=["Human"],
        event="tool_result",
        tool=tool,
        args=args,
        result=result,
        ok=result.get("ok", True),
    )
    append_audit_event(event)
    feed.publish(event)


class ApproveBody(BaseModel):
    approved_by: str = Field(
        min_length=1, description="Name of the human approving the payment. The tool refuses agent names."
    )


class RejectBody(BaseModel):
    decided_by: str = Field(min_length=1, description="Name of the human declining the payment.")
    note: str = Field("", description="Why it was declined. Stored on the request.")


# ---------------------------------------------------------------------------
# The board
# ---------------------------------------------------------------------------


@app.get("/health", summary="Is the API up and connected to the MCP server?")
async def health() -> dict[str, Any]:
    cash = await call_tool("get_cash_balance")
    return {"ok": True, "mcp": "connected", "shop_today": cash["shop_today"], "database": str(WORKING_DB)}


@app.get("/tickets", summary="Every desk ticket and its status")
async def list_tickets(
    status: str | None = Query(None, description="Filter: open, awaiting_approval or resolved."),
) -> dict[str, Any]:
    return await call_tool("list_tickets", {"status": status} if status else {})


@app.get("/tickets/{ticket_id}", summary="One ticket with its approvals, drafts and outcome")
async def get_ticket(ticket_id: int) -> dict[str, Any]:
    return checked(await call_tool("get_ticket", {"ticket_id": ticket_id}))


@app.get("/cash", summary="Checking balance and what is already promised")
async def get_cash() -> dict[str, Any]:
    return await call_tool("get_cash_balance")


# ---------------------------------------------------------------------------
# Running the team
# ---------------------------------------------------------------------------


@app.post("/tickets/{ticket_id}/run", summary="Hand one ticket to the agent team")
async def run_ticket_route(ticket_id: int) -> TicketRunResult:
    """Run the Boss and whoever it delegates to on one open ticket.

    The request stays open until the team finishes, and every step is on `/events/stream`
    while it runs. A ticket that is missing or already closed is refused up front, and so is
    a second run while one is going. A failure part way through comes back as a normal
    response with `error` set, because the partial work and the audit trail still matter to
    whoever is watching the board.
    """
    if gate.busy:
        raise HTTPException(
            status_code=409,
            detail={"ok": False, "reason": f"The board is busy with {gate.busy_with}. Wait for it to finish."},
        )
    with gate.claim(f"ticket {ticket_id}"):
        ticket = checked(await call_tool("get_ticket", {"ticket_id": ticket_id}))["ticket"]
        if ticket["status"] != "open":
            raise HTTPException(
                status_code=409,
                detail={
                    "ok": False,
                    "reason": f"Ticket {ticket_id} is {ticket['status']}; only open tickets can be run. "
                    "Reset the board for a fresh run.",
                    "status": ticket["status"],
                },
            )
        try:
            return await run_ticket(ticket_id, on_event=feed.publish)
        except RuntimeError as e:  # e.g. PORTKEY_API_KEY not set
            raise HTTPException(status_code=503, detail={"ok": False, "reason": str(e)}) from e


@app.get("/events", summary="Recent agent steps and tool calls")
async def get_events(
    since: int = Query(0, ge=0, description="Only steps with a higher seq than this."),
    limit: int = Query(100, ge=1, le=FEED_LIMIT),
    ticket_id: int | None = Query(None, description="Only steps from this ticket's runs."),
) -> dict[str, Any]:
    events = feed.recent(since=since, limit=limit, ticket_id=ticket_id)
    return {"events": events, "count": len(events), "last_seq": feed.last_seq, "busy_with": gate.busy_with}


@app.get("/events/stream", summary="Live stream of agent steps (SSE)")
async def stream_events(request: Request, ticket_id: int | None = None) -> StreamingResponse:
    """Server-sent events, one per agent step, as the team works.

    Each message's SSE `event:` is the step kind (`model_response`, `tool_result`,
    `delegation`, `final`, `run_end`, ...) and `data:` is the same JSON `/events` returns.
    """

    async def steps() -> AsyncIterator[str]:
        with feed.subscribe() as queue:
            yield f": connected, last seq {feed.last_seq}\n\n"
            while not await request.is_disconnected():
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=SSE_KEEPALIVE_S)
                except TimeoutError:
                    yield ": keepalive\n\n"  # keeps an idle connection from being dropped
                    continue
                if ticket_id is None or event.get("ticket_id") == ticket_id:
                    yield f"event: {event['event']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        steps(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# The human approval step: the only way cash moves
# ---------------------------------------------------------------------------


@app.get("/approvals", summary="Payment and purchase requests waiting on a human")
async def list_approvals(
    status: str = Query("pending", description="pending, paid, rejected, or all."),
    ticket_id: int | None = None,
) -> dict[str, Any]:
    args: dict[str, Any] = {"status": None if status == "all" else status}
    if ticket_id is not None:
        args["ticket_id"] = ticket_id
    return await call_tool("list_approval_requests", args)


@app.post("/approvals/{request_id}/approve", summary="Approve a payment: cash leaves checking")
async def approve_request(request_id: int, body: ApproveBody) -> dict[str, Any]:
    """Pay one pending request. This is the only route that touches `cash_accounts`.

    The MCP tool does the work in one transaction: it re-checks the bill and the balance,
    debits checking, writes the `payments` row, marks the invoice paid or moves the lease's
    next due date, and resolves the ticket once nothing is pending on it. It refuses — and
    no cash moves — if the balance would go negative, the request was already decided, or
    the approver is an agent rather than a person.
    """
    args = {"request_id": request_id, "approved_by": body.approved_by}
    result = await call_tool("pay_approved_request", args)
    record_human_decision("pay_approved_request", args, result)
    return checked(result)


@app.post("/approvals/{request_id}/reject", summary="Decline a payment: no cash moves")
async def reject_request(request_id: int, body: RejectBody) -> dict[str, Any]:
    args = {"request_id": request_id, "decided_by": body.decided_by, "note": body.note}
    result = await call_tool("reject_approval_request", args)
    record_human_decision("reject_approval_request", args, result)
    return checked(result)


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------


@app.post("/reset", summary="Put the working database back to the original")
async def reset_board() -> dict[str, Any]:
    """Copy `data/campus_customs.db` over `data/campus_customs_new.db`.

    Tickets go back to open, the balance back to its starting figure, and the workflow
    tables (approval requests, drafts, outcomes) disappear — the MCP server recreates them
    empty on its next call. `output/audit_trail.json` is append-only and is deliberately
    left alone, so the history of earlier runs survives a reset; only the in-memory feed
    the board shows is cleared.
    """
    if gate.busy:
        raise HTTPException(
            status_code=409,
            detail={"ok": False, "reason": f"The board is busy with {gate.busy_with}. Wait for it to finish."},
        )
    with gate.claim("a board reset"):
        if not ORIGINAL_DB.exists():
            raise HTTPException(
                status_code=500, detail={"ok": False, "reason": f"Original database missing at {ORIGINAL_DB}."}
            )
        shutil.copyfile(ORIGINAL_DB, WORKING_DB)
        feed.clear()
        tickets = (await call_tool("list_tickets"))["tickets"]
        cash = await call_tool("get_cash_balance")
    return {
        "ok": True,
        "restored": str(WORKING_DB.relative_to(PROJECT_ROOT)),
        "from": str(ORIGINAL_DB.relative_to(PROJECT_ROOT)),
        "tickets": tickets,
        "cash": cash,
        "audit_trail": "left untouched (append-only); the live event feed was cleared",
    }
