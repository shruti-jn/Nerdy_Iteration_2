import type { StageLatency } from "../types";
import "./LatencyPanel.css";

interface Props {
  stageLatency: StageLatency | null;
}

interface BudgetConfig {
  green: number;
  yellow: number;
}

function dot(ms: number | null, budget: BudgetConfig): string {
  if (ms === null) return "neutral";
  if (ms < budget.green) return "green";
  if (ms < budget.yellow) return "yellow";
  return "red";
}

function fmt(ms: number | null): string {
  return ms !== null ? `${Math.round(ms)}ms` : "\u2014";
}

// Budgets aligned with the execution plan latency targets:
//   STT  < 300ms target / < 1000ms max  (stt_finish_ms includes Deepgram flush wait)
//   LLM  < 200ms target / < 400ms max   (TTFT — time-to-first-token)
//   TTS  < 150ms target / < 300ms max   (TTFA — time-to-first-audio)
//   Total< 500ms target / < 1000ms max  (pipeline wall-clock, excludes speaking time)
const BUDGETS: Record<string, BudgetConfig> = {
  stt:   { green: 300,  yellow: 1000 },  // stt.finish() includes utterance-end detection
  llm:   { green: 200,  yellow: 400 },   // LLM time-to-first-token
  tts:   { green: 150,  yellow: 300 },   // TTS time-to-first-audio
  total: { green: 500,  yellow: 1000 },  // pipeline wall-clock
};

export function LatencyPanel({ stageLatency }: Props) {
  const stages = [
    { label: "STT",   ms: stageLatency?.stt_ms   ?? null, key: "stt" },
    { label: "LLM",   ms: stageLatency?.llm_ms   ?? null, key: "llm" },
    { label: "TTS",   ms: stageLatency?.tts_ms   ?? null, key: "tts" },
    { label: "TOTAL", ms: stageLatency?.total_ms ?? null, key: "total" },
  ];

  return (
    <div className="latency-panel" aria-label="Latency panel">
      {stages.map(({ label, ms, key }) => (
        <div key={key} className="latency-panel__cell">
          <span className="latency-panel__label">{label}</span>
          <span className="latency-panel__value">{fmt(ms)}</span>
          <span
            className={`latency-panel__dot latency-panel__dot--${dot(ms, BUDGETS[key]!)}`}
            aria-label={dot(ms, BUDGETS[key]!)}
          />
        </div>
      ))}
    </div>
  );
}
