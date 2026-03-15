import { useEffect, useRef } from "react";
import type { SessionMode } from "../types";
import "./TutorResponse.css";

interface Props {
  mode: SessionMode;
  streamingWords: string[];
}

export function TutorResponse({ mode, streamingWords }: Props) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const isSpeaking = mode === "tutor-responding" || mode === "tutor-greeting";
  const hasContent = streamingWords.length > 0;

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [streamingWords.length]);

  return (
    <aside className="tutor-response">
      <div className="tutor-response__header">
        <span className="tutor-response__title">Live Transcript</span>
        {isSpeaking && (
          <span className="tutor-response__live-badge">
            <span className="tutor-response__live-dot" />
            Live
          </span>
        )}
      </div>

      <div className="tutor-response__scroll" ref={scrollRef}>
        {!hasContent && !isSpeaking && (
          <div className="tutor-response__empty">
            <p>Words will appear here as they speak.</p>
          </div>
        )}

        {(hasContent || isSpeaking) && (
          <div className="tutor-response__text">
            {streamingWords.map((word, i) => (
              <span
                key={i}
                className="tutor-response__word"
                style={{ animationDelay: `${i * 20}ms` }}
              >
                {word}{" "}
              </span>
            ))}
            {isSpeaking && (
              <span className="tutor-response__cursor" aria-hidden="true" />
            )}
          </div>
        )}
      </div>

      {isSpeaking && (
        <div className="tutor-response__footer">
          <WaveformIndicator />
        </div>
      )}
    </aside>
  );
}

function WaveformIndicator() {
  return (
    <div className="waveform" aria-label="Audio waveform">
      {Array.from({ length: 7 }, (_, i) => (
        <div
          key={i}
          className="waveform__bar"
          style={{ animationDelay: `${i * 80}ms` }}
        />
      ))}
    </div>
  );
}
