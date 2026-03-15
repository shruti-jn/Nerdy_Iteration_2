import type { StageLatency } from "../types";
import "./LatencyPanel.css";

interface Props {
  stageLatency: StageLatency | null;
}

type StageKey = "stt" | "llm" | "tts" | "total";

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
const BUDGETS: Record<StageKey, BudgetConfig> = {
  stt: { green: 300, yellow: 1000 },
  llm: { green: 200, yellow: 400 },
  tts: { green: 150, yellow: 300 },
  total: { green: 500, yellow: 1000 },
};

const TOOLTIPS: Record<StageKey, string> = {
  stt: "STT finalize time (stt_finish_ms): mic release → final transcript.",
  llm: "LLM time-to-first-token (llm_ttf_ms): transcript ready → first token.",
  tts: "TTS time-to-first-audio (tts_ttf_ms): sentence sent → first audio byte.",
  total:
    "Full turn wall-clock (turn_duration_ms): backend pipeline start → end. Not a direct sum of STT + LLM + TTS.",
};

export function LatencyPanel({ stageLatency }: Props) {
  const stages: Array<{ label: string; ms: number | null; key: StageKey }> = [
    { label: "STT", ms: stageLatency?.stt_ms ?? null, key: "stt" },
    { label: "LLM", ms: stageLatency?.llm_ms ?? null, key: "llm" },
    { label: "TTS", ms: stageLatency?.tts_ms ?? null, key: "tts" },
    { label: "TOTAL", ms: stageLatency?.total_ms ?? null, key: "total" },
  ];

  return (
    <div className="latency-panel" aria-label="Latency panel">
      {stages.map(({ label, ms, key }) => {
        const tooltip = TOOLTIPS[key];
        return (
          <div
            key={key}
            className="latency-panel__cell"
            title={tooltip}
            aria-label={`${label} ${fmt(ms)}. ${tooltip}`}
          >
            <span className="latency-panel__label">{label}</span>
            <span className="latency-panel__value">{fmt(ms)}</span>
            <span
              className={`latency-panel__dot latency-panel__dot--${dot(ms, BUDGETS[key])}`}
              aria-label={dot(ms, BUDGETS[key])}
            />
          </div>
        );
      })}
    </div>
  );
}
