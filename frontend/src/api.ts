/** Typed access to the Campus Customs backend (FastAPI on port 8000).
 *
 * The backend is the only thing this app talks to, and the backend is the only
 * thing that talks to the shop's database. Nothing here computes money, status or
 * due dates on its own: every number on screen came from a tool call.
 */

export const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000";

export type TicketStatus = "open" | "awaiting_approval" | "resolved";
export type RequestStatus = "pending" | "paid" | "rejected";
export type AgentName = "Boss" | "Inventory" | "Accounting" | "Facilities" | "Customer Service";

export interface Ticket {
  id: number;
  type: string;
  requester: string;
  subject: string;
  status: TicketStatus;
  created_at: string;
}

/** One ticket with everything the team has attached to it so far. */
export interface TicketDetail {
  found: true;
  shop_today: string;
  ticket: Ticket & {
    sku: string | null;
    size: string | null;
    qty: number | null;
    lease_id: number | null;
    invoice_id: number | null;
    notes: string;
  };
  approval_requests: { id: number; kind: string; payee: string; amount: number; status: string }[];
  message_drafts: { id: number; subject: string; drafted_by: string }[];
  outcome: { outcome: string; decided_by: string; closed_at: string } | null;
}

export interface Cash {
  shop_today: string;
  account: string;
  balance: number;
  as_of: string;
  pending_approval_total: number;
  available_after_pending: number;
}

export interface ApprovalRequest {
  id: number;
  ticket_id: number;
  kind: "invoice" | "rent" | "purchase_order";
  payee: string;
  amount: number;
  reason: string;
  requested_by: string;
  status: RequestStatus;
  created_at: string;
  sku?: string;
  size?: string;
  qty?: number;
  expected_arrival?: string;
  decided_by?: string;
  decision_note?: string;
  payment_id?: number;
}

export type EventKind =
  | "run_start"
  | "model_response"
  | "tool_result"
  | "delegation"
  | "retry"
  | "final"
  | "error"
  | "run_end";

export interface ToolCall {
  tool: string;
  args: Record<string, unknown>;
}

/** One step of one agent's loop — the same shape the backend appends to output/audit_trail.json. */
export interface AgentEvent {
  seq: number;
  timestamp: string;
  run_id: string;
  ticket_id: number;
  agent: string;
  chain: string[];
  event: EventKind;
  step?: number;
  model?: string;
  text?: string;
  tool_calls?: ToolCall[];
  tool?: string;
  args?: Record<string, unknown>;
  result?: unknown;
  ok?: boolean;
  input_tokens?: number;
  output_tokens?: number;
}

export interface BossDecision {
  outcome: string;
  agents_consulted: AgentName[];
  approval_request_ids: number[];
  draft_ids: number[];
  follow_ups: string[];
}

export interface SpecialistReport {
  summary: string;
  facts: string[];
  actions: string[];
  approval_request_ids: number[];
  draft_ids: number[];
  recommendation: string;
}

export interface RunResult {
  run_id: string;
  ticket_id: number;
  status: TicketStatus | null;
  decision: BossDecision | null;
  error: string | null;
  model_requests: number;
  input_tokens: number;
  output_tokens: number;
  delegations: number;
  duration_ms: number;
}

export interface PaymentResult {
  ok: true;
  request_id: number;
  payment_id: number;
  kind: string;
  payee: string;
  amount: number;
  approved_by: string;
  balance_before: number;
  balance_after: number;
  effect: string;
  ticket_id: number;
  ticket_status: TicketStatus;
}

/** A refusal from a shop rule, carrying the reason the tool gave, not a generic HTTP message. */
export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      headers: init?.body ? { "content-type": "application/json" } : undefined,
      ...init,
    });
  } catch {
    throw new ApiError(0, `Can't reach the backend at ${API_BASE}. Is uvicorn running on port 8000?`);
  }
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = (body as { detail?: unknown } | null)?.detail;
    const reason =
      typeof detail === "string"
        ? detail
        : ((detail as { reason?: string; message?: string } | undefined)?.reason ??
          (detail as { message?: string } | undefined)?.message ??
          `Request failed (${response.status}).`);
    throw new ApiError(response.status, reason);
  }
  return body as T;
}

export const getTickets = () => request<{ tickets: Ticket[] }>("/tickets").then((r) => r.tickets);
export const getTicketDetail = (id: number) => request<TicketDetail>(`/tickets/${id}`);
export const getCash = () => request<Cash>("/cash");
export const getApprovals = (status: RequestStatus | "all" = "all") =>
  request<{ requests: ApprovalRequest[] }>(`/approvals?status=${status}`).then((r) => r.requests);
export const getEvents = (since = 0, limit = 400) =>
  request<{ events: AgentEvent[]; last_seq: number; busy_with: string | null }>(
    `/events?since=${since}&limit=${limit}`,
  );

export const runTicket = (ticketId: number) => request<RunResult>(`/tickets/${ticketId}/run`, { method: "POST" });

export const approvePayment = (requestId: number, approvedBy: string) =>
  request<PaymentResult>(`/approvals/${requestId}/approve`, {
    method: "POST",
    body: JSON.stringify({ approved_by: approvedBy }),
  });

export const rejectPayment = (requestId: number, decidedBy: string, note: string) =>
  request<{ ok: true; request_id: number }>(`/approvals/${requestId}/reject`, {
    method: "POST",
    body: JSON.stringify({ decided_by: decidedBy, note }),
  });

export const resetBoard = () => request<{ ok: true }>("/reset", { method: "POST" });

export const money = (amount: number) =>
  amount.toLocaleString("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2 });
