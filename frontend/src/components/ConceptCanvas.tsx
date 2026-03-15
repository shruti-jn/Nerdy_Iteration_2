import { useEffect, useRef, useState } from "react";
import { getConceptScene } from "../conceptScenes";
import "./ConceptCanvas.css";

interface Props {
  diagramId: string;
  stepId: number;
  highlightKeys?: string[];
  unlockedElements?: string[];
  emojiDiagram: string;
  caption: string | null;
  isRecap: boolean;
}

const PHOTOSYNTHESIS_REVEAL_ORDER = [
  "sunlight",
  "water",
  "roots",
  "carbon_dioxide",
  "leaf",
  "chloroplast",
  "chlorophyll",
  "sugar",
  "fruit",
  "oxygen",
] as const;

const PHOTOSYNTHESIS_ELEMENTS = [
  { id: "sunlight", title: "Sunlight", icon: "☀️", x: 15, y: 18, tone: "sun" },
  { id: "water", title: "Water", icon: "💧", x: 18, y: 58, tone: "sky" },
  { id: "roots", title: "Roots", icon: "〰️", x: 37, y: 84, tone: "earth" },
  { id: "carbon_dioxide", title: "CO2", icon: "CO₂", x: 82, y: 24, tone: "sky" },
  { id: "leaf", title: "Leaf", icon: "🍃", x: 58, y: 34, tone: "mint" },
  { id: "chloroplast", title: "Chloroplast", icon: "🟢", x: 63, y: 46, tone: "mint" },
  { id: "chlorophyll", title: "Chlorophyll", icon: "✨", x: 51, y: 48, tone: "mint" },
  { id: "sugar", title: "Sugar", icon: "🍬", x: 73, y: 67, tone: "amber" },
  { id: "fruit", title: "Fruit", icon: "🍎", x: 67, y: 21, tone: "amber" },
  { id: "oxygen", title: "Oxygen", icon: "O₂", x: 85, y: 46, tone: "sky" },
] as const;

function getLayerStatus(layerStepId: number, currentStepId: number, isRecap: boolean) {
  if (isRecap) return "mastered";
  if (layerStepId < currentStepId) return "mastered";
  if (layerStepId === currentStepId) return "revealed";
  return "hidden";
}

function getPlantElementState(
  elementId: string,
  unlocked: Set<string>,
  isRecap: boolean,
) {
  return isRecap || unlocked.has(elementId) ? "revealed" : "hidden";
}

function normalizeElementKey(value: string) {
  return value.trim().toLowerCase().replace(/\s+/g, "_");
}

export function ConceptCanvas({
  diagramId,
  stepId,
  highlightKeys = [],
  unlockedElements = [],
  emojiDiagram,
  caption,
  isRecap,
}: Props) {
  const [visible, setVisible] = useState(true);
  const prevDiagramRef = useRef(`${diagramId}:${stepId}:${emojiDiagram}:${isRecap}`);
  const scene = getConceptScene(diagramId);
  const unlockedSet = new Set<string>(
    (isRecap ? [...PHOTOSYNTHESIS_REVEAL_ORDER] : unlockedElements).map(normalizeElementKey),
  );
  const highlightSet = new Set<string>(highlightKeys.map(normalizeElementKey));

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
      {diagramId === "photosynthesis" ? (
        <div
          className="concept-canvas__scene concept-canvas__scene--photosynthesis concept-canvas__scene--illustration"
          aria-label="Concept diagram"
        >
          <div className="concept-canvas__scene-header">
            <span className="concept-canvas__badge">Greenhouse Map</span>
            <span className="concept-canvas__subhead">
              {isRecap
                ? "Every part of the photosynthesis picture is now glowing."
                : "A single living picture builds itself as each clue is discovered."}
            </span>
          </div>
          <div className="concept-canvas__illustration">
            <div className="concept-canvas__sky-haze" aria-hidden="true" />
            <div className="concept-canvas__ground-band" aria-hidden="true" />
            <div className="concept-canvas__tree-shadow" aria-hidden="true">
              <span className="concept-canvas__tree-canopy concept-canvas__tree-canopy--left" />
              <span className="concept-canvas__tree-canopy concept-canvas__tree-canopy--middle" />
              <span className="concept-canvas__tree-canopy concept-canvas__tree-canopy--right" />
              <span className="concept-canvas__tree-trunk" />
            </div>
            <div className="concept-canvas__sapling" aria-hidden="true">
              <span className="concept-canvas__sapling-stem" />
              <span className="concept-canvas__sapling-leaf concept-canvas__sapling-leaf--left" />
              <span className="concept-canvas__sapling-leaf concept-canvas__sapling-leaf--right" />
            </div>
            <div className="concept-canvas__root-bed" aria-hidden="true">
              <span className="concept-canvas__root-line concept-canvas__root-line--one" />
              <span className="concept-canvas__root-line concept-canvas__root-line--two" />
              <span className="concept-canvas__root-line concept-canvas__root-line--three" />
            </div>

            {PHOTOSYNTHESIS_ELEMENTS.map((element) => {
              const state = getPlantElementState(element.id, unlockedSet, isRecap);
              const active = state === "revealed" && highlightSet.has(element.id);
              return (
                <div
                  key={element.id}
                  className={
                    "concept-canvas__plant-element" +
                    ` concept-canvas__plant-element--${state}` +
                    ` concept-canvas__plant-element--${element.tone}` +
                    (active ? " concept-canvas__plant-element--active" : "")
                  }
                  style={{ left: `${element.x}%`, top: `${element.y}%` }}
                  data-plant-element-id={element.id}
                  data-plant-element-state={state}
                >
                  <span className="concept-canvas__plant-icon" aria-hidden="true">
                    {element.icon}
                  </span>
                  <span className="concept-canvas__plant-label">
                    {state === "revealed" ? element.title : ""}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      ) : scene ? (
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
