import { type Cash, money } from "../api";

interface Props {
  cash: Cash | null;
  live: boolean;
  busy: boolean;
  onReset: () => void;
}

/** The desk header: who we are, what day the shop thinks it is, and the money. */
export function TopBar({ cash, live, busy, onReset }: Props) {
  return (
    <header className="topbar">
      <div className="brand">
        <span className="brand-mark" aria-hidden="true" />
        <div>
          <h1>Campus Customs</h1>
          <p>Operations desk</p>
        </div>
      </div>

      <div className="topbar-meta">
        <span className={`pulse ${live ? "pulse-live" : "pulse-dead"}`} />
        <span className="muted">{live ? "Live" : "Reconnecting"}</span>
        {cash && <span className="divider" />}
        {cash && <span className="muted">Shop date {cash.shop_today}</span>}
      </div>

      <div className="balance" aria-label="Checking balance">
        <span className="balance-label">Checking</span>
        <strong className="balance-figure">{cash ? money(cash.balance) : "—"}</strong>
        {cash && cash.pending_approval_total > 0 && (
          <span className="balance-pending">
            {money(cash.pending_approval_total)} awaiting approval &middot; {money(cash.available_after_pending)} free
          </span>
        )}
      </div>

      <button className="btn btn-ghost" onClick={onReset} disabled={busy} title="Restore the original database">
        Reset board
      </button>
    </header>
  );
}
