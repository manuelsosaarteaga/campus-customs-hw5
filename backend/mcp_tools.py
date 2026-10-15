"""The agent team's connection to the Campus Customs MCP server, and which tools each agent may use.

Every shop fact the agents see comes through this MCP connection. There is no second
tools layer that reads the database directly.
"""

import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastmcp import Client
from fastmcp.client.transports import StdioTransport
from pydantic_ai import RunContext
from pydantic_ai.mcp import CallToolFunc, MCPToolset
from pydantic_ai.toolsets import FilteredToolset

from models import AgentName, TicketDeps

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SERVER_PATH = PROJECT_ROOT / "mcp_server" / "server.py"

# Least privilege: each agent sees only the tools its job needs. Only Accounting can prepare
# payments, only Customer Service can save drafts, and no agent ever sees the backend-only tools.
AGENT_TOOLS: dict[AgentName, frozenset[str]] = {
    "Boss": frozenset({"get_ticket", "list_tickets", "get_cash_balance", "list_approval_requests", "list_message_drafts"}),
    "Inventory": frozenset({"get_ticket", "check_stock_and_price", "list_vendors", "get_vendor_invoice"}),
    "Accounting": frozenset({
        "get_ticket", "get_cash_balance", "get_vendor_invoice", "list_open_invoices", "list_vendors",
        "check_stock_and_price", "quote_bulk_price", "list_approval_requests", "list_payments",
        "request_invoice_payment", "request_rent_payment", "request_purchase_order",
    }),
    "Facilities": frozenset({"get_ticket", "get_lease", "list_approval_requests"}),
    "Customer Service": frozenset({
        "get_ticket", "check_stock_and_price", "quote_bulk_price", "save_message_draft", "list_message_drafts",
    }),
}
# Called only by the backend: closing a ticket after the Boss decides, and the human approve/reject route.
BACKEND_ONLY_TOOLS = frozenset({"close_ticket", "pay_approved_request", "reject_approval_request"})
# "Who did this" arguments are filled in from the calling agent, so an agent can't sign as someone else.
SIGNED_ARGS = {
    "request_invoice_payment": "requested_by",
    "request_rent_payment": "requested_by",
    "request_purchase_order": "requested_by",
    "save_message_draft": "drafted_by",
}

assert not any(tools & BACKEND_ONLY_TOOLS for tools in AGENT_TOOLS.values()), "agents must never see backend-only tools"


async def _sign_as_agent(ctx: RunContext[TicketDeps], call_tool: CallToolFunc, name: str, args: dict[str, Any]) -> Any:
    if name in SIGNED_ARGS:
        args = {**args, SIGNED_ARGS[name]: ctx.deps.agent}
    return await call_tool(name, args)


@lru_cache(maxsize=1)
def shop_toolset() -> MCPToolset:
    """One stdio connection to mcp_server/server.py, shared by every agent (and the backend's own calls)."""
    transport = StdioTransport(command=sys.executable, args=[str(SERVER_PATH)], cwd=str(PROJECT_ROOT))
    return MCPToolset(Client(transport), process_tool_call=_sign_as_agent)


def toolset_for(agent: AgentName) -> FilteredToolset:
    allowed = AGENT_TOOLS[agent]
    return shop_toolset().filtered(lambda ctx, tool_def: tool_def.name in allowed)
