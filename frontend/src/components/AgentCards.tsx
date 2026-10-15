import type { AgentCard } from "../runView";

const STATUS_LABEL = { idle: "Idle", working: "Working", reported: "Reported" } as const;

const agentClass = (agent: string) => `agent-${agent.toLowerCase().replace(/\s+/g, "-")}`;

export function AgentCards({ cards }: { cards: AgentCard[] }) {
  return (
    <section className="panel agents">
      <div className="panel-head">
        <h2>The team</h2>
        <span className="count">{cards.filter((c) => c.status === "reported").length} reported</span>
      </div>

      <ul className="agent-list">
        {cards.map((card) => (
          <li key={card.name} className={`agent-card agent-card-${card.status}`}>
            <div className="agent-head">
              <span className={`chip ${agentClass(card.name)}`}>{card.name}</span>
              <span className={`agent-status agent-status-${card.status}`}>
                {card.status === "working" && <span className="pulse pulse-live" />}
                {STATUS_LABEL[card.status]}
              </span>
            </div>

            <p className="agent-role">{card.role}</p>

            {card.chain && card.chain.length > 1 && (
              <p className="agent-chain">{card.chain.join(" → ")}</p>
            )}

            {(card.steps > 0 || card.tools > 0) && (
              <p className="agent-counts">
                <span>{card.steps} turns</span>
                <span className="divider" />
                <span>{card.tools} tool calls</span>
              </p>
            )}

            {card.decision && (
              <div className="agent-report">
                <p>{card.decision.outcome}</p>
                {card.decision.agents_consulted.length > 0 && (
                  <p className="agent-meta">Consulted {card.decision.agents_consulted.join(", ")}</p>
                )}
              </div>
            )}

            {card.report && (
              <div className="agent-report">
                <p>{card.report.summary}</p>
                {card.report.recommendation && <p className="agent-meta">{card.report.recommendation}</p>}
              </div>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
