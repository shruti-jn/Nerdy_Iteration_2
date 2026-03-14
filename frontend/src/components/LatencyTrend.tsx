import type { TurnLatency } from "../types";
import "./LatencyTrend.css";

interface Props {
  history: TurnLatency[];
}

function fmt(ms: number | null): string {
  return ms !== null ? `${Math.round(ms)}ms` : "—";
}

/** Returns true when `ms` is >20% worse than `prev`. */
function isRegression(ms: number | null, prev: number | null): boolean {
  if (ms === null || prev === null || prev === 0) return false;
  return ms > prev * 1.2;
}

/** ↑ when worse (higher ms), ↓ when better, "" when equal/unknown. */
function arrow(ms: number | null, prev: number | null): string {
  if (ms === null || prev === null) return "";
  if (ms > prev) return "↑";
  if (ms < prev) return "↓";
  return "";
}

export function LatencyTrend({ history }: Props) {
  if (history.length === 0) {
    return (
      <div className="latency-trend latency-trend--empty">
        No turns recorded yet.
      </div>
    );
  }

  return (
    <div className="latency-trend" role="table" aria-label="Latency trend">
      <div className="latency-trend__header" role="row">
        <span role="columnheader">Turn</span>
        <span role="columnheader">STT</span>
        <span role="columnheader">LLM</span>
        <span role="columnheader">TTS</span>
        <span role="columnheader">Total</span>
      </div>
      {history.map((entry, idx) => {
        const prev = idx > 0 ? history[idx - 1]! : null;
        return (
          <div key={entry.turn} className="latency-trend__row" role="row">
            <span className="latency-trend__cell" role="cell">{entry.turn}</span>
            <span
              className={`latency-trend__cell${isRegression(entry.stt_ms, prev?.stt_ms ?? null) ? " latency-trend__cell--red" : ""}`}
              role="cell"
            >
              {fmt(entry.stt_ms)}
            </span>
            <span
              className={`latency-trend__cell${isRegression(entry.llm_ms, prev?.llm_ms ?? null) ? " latency-trend__cell--red" : ""}`}
              role="cell"
            >
              {fmt(entry.llm_ms)}
            </span>
            <span
              className={`latency-trend__cell${isRegression(entry.tts_ms, prev?.tts_ms ?? null) ? " latency-trend__cell--red" : ""}`}
              role="cell"
            >
              {fmt(entry.tts_ms)}
            </span>
            <span
              className={`latency-trend__cell latency-trend__cell--total${isRegression(entry.total_ms, prev?.total_ms ?? null) ? " latency-trend__cell--red" : ""}`}
              role="cell"
            >
              {fmt(entry.total_ms)}
              {prev && (
                <span className="latency-trend__arrow">
                  {arrow(entry.total_ms, prev.total_ms)}
                </span>
              )}
            </span>
          </div>
        );
      })}
    </div>
  );
}
