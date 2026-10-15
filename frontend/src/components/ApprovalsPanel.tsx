import { useState } from "react";
import { type ApprovalRequest, money } from "../api";

const KIND_LABEL: Record<string, string> = {
  invoice: "Vendor invoice",
  rent: "Rent",
  purchase_order: "Purchase order",
};

interface Props {
  approvals: ApprovalRequest[];
  approver: string;
  busy: boolean;
  onApproverChange: (name: string) => void;
  onApprove: (id: number) => Promise<void>;
  onReject: (id: number) => Promise<void>;
  error: string | null;
}

/** The one place in the whole project where a person, not an agent, moves money. */
export function ApprovalsPanel({ approvals, approver, busy, onApproverChange, onApprove, onReject, error }: Props) {
  const [pendingId, setPendingId] = useState<number | null>(null);
  const pending = approvals.filter((r) => r.status === "pending");
  const decided = approvals.filter((r) => r.status !== "pending");

  const act = async (id: number, action: (id: number) => Promise<void>) => {
    setPendingId(id);
    try {
      await action(id);
    } finally {
      setPendingId(null);
    }
  };

  return (
    <section className="panel approvals">
      <div className="panel-head">
        <h2>Needs a human</h2>
        {pending.length > 0 && <span className="count count-alert">{pending.length}</span>}
      </div>

      <label className="approver">
        <span>Approving as</span>
        <input
          value={approver}
          placeholder="Your name"
          onChange={(e) => onApproverChange(e.target.value)}
          spellCheck={false}
        />
      </label>

      {error && <p className="inline-error">{error}</p>}

      {pending.length === 0 && <p className="muted approvals-empty">No payment is waiting on you.</p>}

      <ul className="approval-list">
        {pending.map((request) => (
          <li key={request.id} className="approval">
            <div className="approval-head">
              <span className="pill pill-kind">{KIND_LABEL[request.kind] ?? request.kind}</span>
              <span className="muted">#{request.id} &middot; ticket {request.ticket_id}</span>
            </div>

            <p className="approval-amount">{money(request.amount)}</p>
            <p className="approval-payee">to {request.payee}</p>
            <p className="approval-reason">{request.reason}</p>
            <p className="approval-meta">
              prepared by {request.requested_by}
              {request.qty ? ` · ${request.qty} × ${request.sku} ${request.size}` : ""}
              {request.expected_arrival ? ` · arrives ${request.expected_arrival}` : ""}
            </p>

            <div className="approval-actions">
              <button
                className="btn btn-approve"
                disabled={busy || !approver.trim() || pendingId === request.id}
                onClick={() => void act(request.id, onApprove)}
              >
                {pendingId === request.id ? "Paying…" : `Approve ${money(request.amount)}`}
              </button>
              <button
                className="btn btn-ghost"
                disabled={busy || !approver.trim() || pendingId === request.id}
                onClick={() => void act(request.id, onReject)}
              >
                Decline
              </button>
            </div>
            {!approver.trim() && <p className="hint">Type your name above — an agent can't approve its own payment.</p>}
          </li>
        ))}
      </ul>

      {decided.length > 0 && (
        <div className="decided">
          <h3>Already decided</h3>
          <ul>
            {decided.map((request) => (
              <li key={request.id}>
                <span className={`badge ${request.status === "paid" ? "badge-ok" : "badge-bad"}`}>
                  {request.status}
                </span>
                <span className="decided-amount">{money(request.amount)}</span>
                <span className="muted">
                  {request.payee} &middot; {request.decided_by ?? "—"}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
