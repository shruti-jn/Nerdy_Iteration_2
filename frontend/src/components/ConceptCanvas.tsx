import { useEffect, useRef, useState } from "react";
import { getConceptScene } from "../conceptScenes";
import "./ConceptCanvas.css";

interface Props {
  diagramId: string;
  stepId: number;
  emojiDiagram: string;
  caption: string | null;
  isRecap: boolean;
}

function getLayerStatus(layerStepId: number, currentStepId: number, isRecap: boolean) {
  if (isRecap) return "mastered";
  if (layerStepId < currentStepId) return "mastered";
  if (layerStepId === currentStepId) return "revealed";
  return "hidden";
}

export function ConceptCanvas({ diagramId, stepId, emojiDiagram, caption, isRecap }: Props) {
  const [visible, setVisible] = useState(true);
  const prevDiagramRef = useRef(`${diagramId}:${stepId}:${emojiDiagram}:${isRecap}`);
  const scene = getConceptScene(diagramId);

  useEffect(() => {
    const nextSignature = `${diagramId}:${stepId}:${emojiDiagram}:${isRecap}`;
    if (prevDiagramRef.current === nextSignature) return;
    prevDiagramRef.current = nextSignature;
    setVisible(false);
    const id = setTimeout(() => setVisible(true), 180);
    return () => clearTimeout(id);
  }, [diagramId, stepId, emojiDiagram, isRecap]);

  return (
    <div
      className={
        "concept-canvas" +
        (isRecap ? " concept-canvas--recap" : "") +
        (visible ? " concept-canvas--visible" : " concept-canvas--hidden")
      }
    >
      {scene ? (
        <div
          className={`concept-canvas__scene concept-canvas__scene--${scene.id}`}
          aria-label="Concept diagram"
        >
          <div className="concept-canvas__scene-header">
            <span className="concept-canvas__badge">{scene.badge}</span>
            <span className="concept-canvas__subhead">
              {isRecap ? "Full scene unlocked" : scene.subhead}
            </span>
          </div>
          <div className="concept-canvas__scene-grid">
            {scene.layers.map((layer) => {
              const status = getLayerStatus(layer.stepId, stepId, isRecap);
              return (
                <div
                  key={layer.id}
                  className={
                    "concept-canvas__layer" +
                    ` concept-canvas__layer--${status}` +
                    ` concept-canvas__layer--${layer.tone}`
                  }
                  style={{ left: `${layer.x}%`, top: `${layer.y}%` }}
                  data-layer-id={layer.id}
                  data-layer-status={status}
                >
                  <span className="concept-canvas__layer-icon" aria-hidden="true">
                    {status === "hidden" ? "✦" : layer.icon}
                  </span>
                  <span className="concept-canvas__layer-label">
                    {status === "hidden" ? "Locked" : layer.title}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      ) : (
        <div className="concept-canvas__diagram" aria-label="Concept diagram">
          {emojiDiagram}
        </div>
      )}
      {caption && (
        <p className="concept-canvas__caption">{caption}</p>
      )}
      {isRecap && (
        <span className="concept-canvas__check" aria-label="Complete">✓</span>
      )}
    </div>
  );
}
