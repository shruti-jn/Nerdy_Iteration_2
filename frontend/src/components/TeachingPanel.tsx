import { useEffect, useRef } from "react";
import type { SessionMode, LessonVisualState } from "../types";
import { StepProgress } from "./StepProgress";
import { ConceptCanvas } from "./ConceptCanvas";
import "./StepProgress.css";
import "./ConceptCanvas.css";
import "./TeachingPanel.css";

interface Props {
  mode: SessionMode;
  streamingWords: string[];
  visual: LessonVisualState | null;
}

export function TeachingPanel({ mode, streamingWords, visual }: Props) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const isSpeaking = mode === "tutor-responding" || mode === "tutor-greeting";
  const hasContent = streamingWords.length > 0;

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [streamingWords.length]);

  return (
    <aside className="teaching-panel">
      <div className="teaching-panel__header">
        <span className="teaching-panel__title">
          {visual ? "Concept Map" : "Live Transcript"}
        </span>
        {isSpeaking && (
          <span className="teaching-panel__live-badge">
            <span className="teaching-panel__live-dot" />
            Live
          </span>
        )}
      </div>

      {visual && (
        <div className="teaching-panel__visual">
          <StepProgress
            currentStep={visual.stepId}
            totalSteps={visual.progressTotal ?? visual.totalSteps}
            stepLabel={visual.progressLabel ?? visual.stepLabel}
            isRecap={visual.isRecap}
            completedCount={visual.progressCompleted}
          />
          <ConceptCanvas
            diagramId={visual.diagramId}
            stepId={visual.stepId}
            highlightKeys={visual.highlightKeys}
            unlockedElements={visual.unlockedElements}
            emojiDiagram={visual.emojiDiagram}
            caption={visual.caption}
            isRecap={visual.isRecap}
          />
        </div>
      )}

      {visual && <div className="teaching-panel__divider" />}

      <div className="teaching-panel__scroll" ref={scrollRef}>
        {(hasContent || isSpeaking) && (
          <div className="teaching-panel__text">
            {streamingWords.map((word, i) => (
              <span
                key={i}
                className="teaching-panel__word"
                style={{ animationDelay: `${i * 20}ms` }}
              >
                {word}{" "}
              </span>
            ))}
            {isSpeaking && (
              <span className="teaching-panel__cursor" aria-hidden="true" />
            )}
          </div>
        )}
      </div>

      {isSpeaking && (
        <div className="teaching-panel__footer">
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
