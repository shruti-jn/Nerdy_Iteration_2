import { useCallback, useRef } from "react";
import type { SessionMode } from "../types";
import "./BottomBar.css";

interface Props {
  mode: SessionMode;
  latencyMs: number | null;
  onMicPress: () => void;
  onMicRelease: () => void;
  onBargeIn: () => void;
}

export function BottomBar({
  mode,
  latencyMs,
  onMicPress,
  onMicRelease,
  onBargeIn,
}: Props) {
  const isRecording = mode === "student-speaking";
  const isTutorSpeaking = mode === "tutor-responding" || mode === "tutor-greeting";
  const isGreeting = mode === "tutor-greeting";

  // Track whether the current interaction started from a touch event so we
  // can suppress the redundant mouse events that browsers fire after touch.
  const isTouchRef = useRef(false);

  const handlePointerPress = useCallback(
    (e: React.MouseEvent | React.TouchEvent) => {
      if (e.type === "touchstart") {
        isTouchRef.current = true;
        e.preventDefault(); // prevent subsequent mouse* events
      } else if (isTouchRef.current) {
        return; // ignore mousedown that follows touchstart
      }
      onMicPress();
    },
    [onMicPress],
  );

  const handlePointerRelease = useCallback(
    (e: React.MouseEvent | React.TouchEvent) => {
      if (e.type === "touchend" || e.type === "touchcancel") {
        isTouchRef.current = false;
        e.preventDefault();
      } else if (isTouchRef.current) {
        return; // ignore mouseup that follows touchend
      }
      onMicRelease();
    },
    [onMicRelease],
  );

  return (
    <footer className="bottom-bar">
      {/* Left spacer (mirrors right side for centering) */}
      <div className="bottom-bar__side bottom-bar__side--left">
        {isRecording && <WaveformMic />}
      </div>

      {/* Center: mic button */}
      <div className="bottom-bar__center">
        <button
          className={[
            "mic-btn",
            isRecording && "mic-btn--recording",
            !isRecording && !isTutorSpeaking && "mic-btn--idle",
          ]
            .filter(Boolean)
            .join(" ")}
          onMouseDown={handlePointerPress}
          onMouseUp={handlePointerRelease}
          onMouseLeave={isRecording ? handlePointerRelease : undefined}
          onTouchStart={handlePointerPress}
          onTouchEnd={handlePointerRelease}
          onTouchCancel={handlePointerRelease}
          aria-label={isRecording ? "Stop recording" : "Hold to speak"}
          aria-pressed={isRecording}
          disabled={isTutorSpeaking}
        >
          <MicIcon active={isRecording} />
        </button>
        <span className="mic-btn__hint">
          {isRecording ? "Release to send" : isGreeting ? "Socrates 6 is introducing the topic…" : isTutorSpeaking ? "Tutor speaking…" : "Hold to speak"}
        </span>
      </div>

      {/* Right: barge-in + latency */}
      <div className="bottom-bar__side bottom-bar__side--right">
        <button
          className={[
            "barge-btn",
            isTutorSpeaking && "barge-btn--active",
          ]
            .filter(Boolean)
            .join(" ")}
          onClick={onBargeIn}
          aria-label="Interrupt tutor"
          disabled={!isTutorSpeaking || isGreeting}
        >
          <StopIcon />
          <span>Interrupt</span>
        </button>

        {latencyMs !== null && (
          <div className="latency-badge" title="End-to-end response latency">
            <span className="latency-badge__icon">⚡</span>
            <span className="latency-badge__value">~{latencyMs}ms</span>
          </div>
        )}
      </div>
    </footer>
  );
}

function MicIcon({ active }: { active: boolean }) {
  return (
    <svg
      width="26"
      height="26"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <rect x="9" y="2" width="6" height="11" rx="3" fill={active ? "currentColor" : "none"} />
      <path d="M5 10a7 7 0 0 0 14 0" />
      <line x1="12" y1="19" x2="12" y2="22" />
      <line x1="8" y1="22" x2="16" y2="22" />
    </svg>
  );
}

function StopIcon() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="currentColor"
      aria-hidden="true"
    >
      <rect x="4" y="4" width="16" height="16" rx="2" />
    </svg>
  );
}

function WaveformMic() {
  return (
    <div className="waveform-mic" aria-label="Recording waveform">
      {Array.from({ length: 5 }, (_, i) => (
        <div
          key={i}
          className="waveform-mic__bar"
          style={{ animationDelay: `${i * 100}ms` }}
        />
      ))}
    </div>
  );
}
