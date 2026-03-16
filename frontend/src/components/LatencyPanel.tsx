import type { StageLatency } from "../types";
import "./LatencyPanel.css";

interface Props {
  stageLatency: StageLatency | null;
}

type StageKey = "stt" | "llm" | "tts" | "total" | "e2e" | "complete" | "sync";

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

/** Dot status for signed metrics — uses absolute value for threshold comparison. */
function dotAbs(ms: number | null, budget: BudgetConfig): string {
  if (ms === null) return "neutral";
  const abs = Math.abs(ms);
  if (abs < budget.green) return "green";
  if (abs < budget.yellow) return "yellow";
  return "red";
}

function fmt(ms: number | null): string {
  return ms !== null ? `${Math.round(ms)}ms` : "\u2014";
}

/** Format signed metrics with an explicit + prefix for positive values. */
function fmtSigned(ms: number | null): string {
  if (ms === null) return "\u2014";
  const sign = ms > 0 ? "+" : "";
  return `${sign}${Math.round(ms)}ms`;
}

// Budgets aligned with the execution plan latency targets:
//   STT  < 300ms target / < 1000ms max  (stt_finish_ms includes Deepgram flush wait)
//   LLM  < 200ms target / < 400ms max   (TTFT — time-to-first-token)
//   TTS  < 150ms target / < 300ms max   (TTFA — time-to-first-audio)
//   Total< 500ms target / < 1000ms max  (pipeline wall-clock, excludes speaking time)
//   E2E  < 500ms target / < 1000ms max  (mic release → first audio byte in browser)
//   DONE < 3000ms target / < 5000ms max (mic release → last audio chunk played)
//   SYNC < ±80ms target / < ±200ms max  (abs lip-sync offset)
const BUDGETS: Record<StageKey, BudgetConfig> = {
  stt: { green: 300, yellow: 1000 },
  llm: { green: 200, yellow: 400 },
  tts: { green: 150, yellow: 300 },
  total: { green: 500, yellow: 1000 },
  e2e: { green: 500, yellow: 1000 },
  complete: { green: 3000, yellow: 5000 },
  sync: { green: 80, yellow: 200 },
};

const TOOLTIPS: Record<StageKey, string> = {
  stt: "STT finalize time (stt_finish_ms): mic release → final transcript.",
  llm: "LLM time-to-first-token (llm_ttf_ms): transcript ready → first token.",
  tts: "TTS time-to-first-audio (tts_ttf_ms): sentence sent → first audio byte.",
  total:
    "Full turn wall-clock (turn_duration_ms): backend pipeline start → end. Not a direct sum of STT + LLM + TTS.",
  e2e: "E2E (frontend_e2e_ms): mic release → first audio byte played in browser.",
  complete:
    "Response complete: mic release → full tutor response finished playing.",
  sync:
    "Lip-sync offset (T_video \u2212 T_audio): positive = video frame arrived after audio (video lags); negative = audio started after video. Target \u00b180ms.",
};

interface StageConfig {
  label: string;
  ms: number | null;
  key: StageKey;
  /** If true, the value is signed and both display and dot use the absolute value for thresholds. */
  signed?: boolean;
}

export function LatencyPanel({ stageLatency }: Props) {
  const stages: StageConfig[] = [
    { label: "STT", ms: stageLatency?.stt_ms ?? null, key: "stt" },
    { label: "LLM", ms: stageLatency?.llm_ms ?? null, key: "llm" },
    { label: "TTS", ms: stageLatency?.tts_ms ?? null, key: "tts" },
    { label: "TOTAL", ms: stageLatency?.total_ms ?? null, key: "total" },
    { label: "E2E", ms: stageLatency?.e2e_ms ?? null, key: "e2e" },
    { label: "DONE", ms: stageLatency?.response_complete_ms ?? null, key: "complete" },
    { label: "SYNC", ms: stageLatency?.lip_sync_ms ?? null, key: "sync", signed: true },
  ];

  return (
    <div className="latency-panel" aria-label="Latency panel">
      {stages.map(({ label, ms, key, signed }) => {
        const tooltip = TOOLTIPS[key];
        const dotClass = signed ? dotAbs(ms, BUDGETS[key]) : dot(ms, BUDGETS[key]);
        const displayValue = signed ? fmtSigned(ms) : fmt(ms);
        return (
          <div
            key={key}
            className="latency-panel__cell"
            title={tooltip}
            aria-label={`${label} ${displayValue}. ${tooltip}`}
          >
            <span className="latency-panel__label">{label}</span>
            <span className="latency-panel__value">{displayValue}</span>
            <span
              className={`latency-panel__dot latency-panel__dot--${dotClass}`}
              aria-label={dotClass}
            />
          </div>
        );
      })}
    </div>
  );
}
