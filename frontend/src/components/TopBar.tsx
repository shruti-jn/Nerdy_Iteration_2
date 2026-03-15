import { useState } from "react";
import type { SessionStore } from "../types";
import { LatencyPanel } from "./LatencyPanel";
import { LatencyTrend } from "./LatencyTrend";
import "./TopBar.css";

interface Props {
  store: SessionStore;
}

export function TopBar({ store }: Props) {
  const { topic, grade, turnNumber, totalTurns, stageLatency, latencyHistory } = store;
  const [trendOpen, setTrendOpen] = useState(false);

  return (
    <header className="topbar">
      <div className="topbar__brand">
        <span className="topbar__logo">N</span>
        <span className="topbar__name">Socrates VI</span>
      </div>

      <div className="topbar__topic">
        <span className="topbar__topic-text">{topic}</span>
        <span className="topbar__separator">&middot;</span>
        <span className="topbar__grade">Grade {grade}</span>
      </div>

      <button
        className="topbar__latency-toggle"
        onClick={() => setTrendOpen((o) => !o)}
        aria-label={trendOpen ? "Hide latency trend" : "Show latency trend"}
        aria-expanded={trendOpen}
      >
        <LatencyPanel stageLatency={stageLatency} />
        <span className="topbar__trend-caret">{trendOpen ? "\u25B2" : "\u25BC"}</span>
      </button>

      {trendOpen && <LatencyTrend history={latencyHistory} />}

      <div className="topbar__turn">
        <span className="topbar__turn-label">Turn</span>
        <span className="topbar__turn-count">
          {turnNumber}
          <span className="topbar__turn-total"> / {totalTurns}</span>
        </span>
      </div>
    </header>
  );
}
