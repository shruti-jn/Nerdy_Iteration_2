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
  "carbon_dioxide",
  "leaf",
  "chloroplast",
  "chlorophyll",
  "sugar",
  "oxygen",
] as const;

const PHOTOSYNTHESIS_ELEMENTS = {
  sunlight: { id: "sunlight", title: "Sunlight", icon: "☀️", tone: "sun", description: "energy" },
  water: { id: "water", title: "Water", icon: "💧", tone: "sky", description: "from roots" },
  carbon_dioxide: { id: "carbon_dioxide", title: "Carbon Dioxide", icon: "CO₂", tone: "sky", description: "from air" },
  leaf: { id: "leaf", title: "Leaf", icon: "🍃", tone: "mint", description: "where it happens" },
  chloroplast: { id: "chloroplast", title: "Chloroplast", icon: "🟢", tone: "mint", description: "tiny kitchen" },
  chlorophyll: { id: "chlorophyll", title: "Chlorophyll", icon: "✨", tone: "mint", description: "captures light" },
  sugar: { id: "sugar", title: "Glucose", icon: "🍬", tone: "amber", description: "plant food" },
  oxygen: { id: "oxygen", title: "Oxygen", icon: "O₂", tone: "sky", description: "released" },
} as const;

const PHOTOSYNTHESIS_OUTER_NODES = [
  { id: "sunlight", className: "concept-canvas__diagram-node--sunlight" },
  { id: "carbon_dioxide", className: "concept-canvas__diagram-node--carbon-dioxide" },
  { id: "water", className: "concept-canvas__diagram-node--water" },
  { id: "oxygen", className: "concept-canvas__diagram-node--oxygen" },
  { id: "sugar", className: "concept-canvas__diagram-node--sugar" },
] as const;

const PHOTOSYNTHESIS_FACTORY_NODES = ["leaf", "chloroplast", "chlorophyll"] as const;
const PHOTOSYNTHESIS_INPUTS = ["sunlight", "water", "carbon_dioxide"] as const;
const PHOTOSYNTHESIS_OUTPUTS = ["sugar", "oxygen"] as const;
const PHOTOSYNTHESIS_FACTORY_STEP_ID = 2;

const ELEMENT_KEY_ALIASES: Record<string, string> = {
  "carbon dioxide": "carbon_dioxide",
  co2: "carbon_dioxide",
  "co_2": "carbon_dioxide",
  glucose: "sugar",
  "plant food": "sugar",
  "food for itself": "sugar",
  "its own food": "sugar",
  o2: "oxygen",
};

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
  const normalized = value.trim().toLowerCase().replace(/\s+/g, "_");
  return ELEMENT_KEY_ALIASES[normalized] ?? normalized;
}

function getConnectorState(
  elementIds: readonly string[],
  unlocked: Set<string>,
  isRecap: boolean,
) {
  return isRecap || elementIds.some((elementId) => unlocked.has(elementId))
    ? "revealed"
    : "hidden";
}

function PhotosynthesisPlantGraphic({ highlightLeafFactory }: { highlightLeafFactory: boolean }) {
  return (
    <svg
      className="concept-canvas__plant-svg"
      viewBox="0 0 240 260"
      aria-hidden="true"
    >
      <defs>
        <linearGradient id="plantStem" x1="0%" x2="0%" y1="0%" y2="100%">
          <stop offset="0%" stopColor="#84cc16" />
          <stop offset="100%" stopColor="#166534" />
        </linearGradient>
        <linearGradient id="leafFill" x1="0%" x2="100%" y1="0%" y2="100%">
          <stop offset="0%" stopColor="#86efac" />
          <stop offset="100%" stopColor="#15803d" />
        </linearGradient>
        <linearGradient id="rootStroke" x1="0%" x2="100%" y1="0%" y2="100%">
          <stop offset="0%" stopColor="#f59e0b" />
          <stop offset="100%" stopColor="#78350f" />
        </linearGradient>
      </defs>

      <ellipse cx="120" cy="114" rx="78" ry="86" className="concept-canvas__plant-halo" />
      <path
        d="M120 210 C119 178 117 150 118 118 C119 94 121 72 124 44"
        className="concept-canvas__plant-stem-path"
      />

      <g className="concept-canvas__plant-leaves">
        <path d="M118 68 C90 58 74 42 68 22 C92 18 112 30 120 54 Z" className="concept-canvas__plant-leaf-path" />
        <path d="M123 64 C149 52 164 34 170 16 C144 14 128 26 121 48 Z" className="concept-canvas__plant-leaf-path" />
        <path d="M117 98 C87 94 72 82 62 60 C88 58 108 68 118 86 Z" className="concept-canvas__plant-leaf-path" />
        <path d="M123 94 C151 90 168 74 178 52 C151 50 132 62 122 82 Z" className="concept-canvas__plant-leaf-path" />
        <path d="M117 128 C90 132 74 126 56 108 C82 102 104 106 118 118 Z" className="concept-canvas__plant-leaf-path" />
        <path d="M123 126 C149 132 166 124 184 104 C158 98 136 102 122 114 Z" className="concept-canvas__plant-leaf-path" />
        <path d="M118 154 C95 166 80 168 64 160 C82 142 102 138 118 144 Z" className="concept-canvas__plant-leaf-path" />
        <path d="M122 152 C144 166 160 168 176 160 C158 142 138 138 122 144 Z" className="concept-canvas__plant-leaf-path" />
      </g>

      <g className="concept-canvas__plant-veins">
        <path d="M118 86 C102 82 90 72 82 58" className="concept-canvas__plant-vein-path" />
        <path d="M122 82 C138 76 150 62 160 44" className="concept-canvas__plant-vein-path" />
        <path d="M118 118 C102 114 88 110 74 100" className="concept-canvas__plant-vein-path" />
        <path d="M122 114 C138 112 152 104 166 92" className="concept-canvas__plant-vein-path" />
      </g>

      <g className="concept-canvas__plant-roots">
        <path d="M120 208 C112 226 94 238 70 248" className="concept-canvas__plant-root-path" />
        <path d="M120 208 C124 226 146 238 170 248" className="concept-canvas__plant-root-path" />
        <path d="M120 208 C108 224 104 242 102 254" className="concept-canvas__plant-root-path" />
        <path d="M120 208 C130 224 136 240 138 254" className="concept-canvas__plant-root-path" />
        <path d="M110 220 C96 228 84 236 80 248" className="concept-canvas__plant-root-path" />
        <path d="M130 220 C144 228 156 236 160 248" className="concept-canvas__plant-root-path" />
      </g>

      <circle
        cx="154"
        cy="111"
        r="18"
        className={
          "concept-canvas__plant-highlight-ring" +
          (highlightLeafFactory ? " concept-canvas__plant-highlight-ring--active" : "")
        }
      />
      <circle
        cx="154"
        cy="111"
        r="7"
        className={
          "concept-canvas__plant-highlight-dot" +
          (highlightLeafFactory ? " concept-canvas__plant-highlight-dot--active" : "")
        }
      />
    </svg>
  );
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
  const reactionActive = isRecap || highlightSet.has("chlorophyll") || highlightSet.has("leaf");
  const hasFactoryReveal = isRecap || PHOTOSYNTHESIS_FACTORY_NODES.some((elementId) => unlockedSet.has(elementId));
  const lessonAtLeafFactory =
    isRecap ||
    stepId >= PHOTOSYNTHESIS_FACTORY_STEP_ID ||
    hasFactoryReveal ||
    PHOTOSYNTHESIS_FACTORY_NODES.some((elementId) => highlightSet.has(elementId));
  const leafFactoryActive =
    reactionActive ||
    highlightSet.has("chloroplast") ||
    hasFactoryReveal;
  const showLeafZoomDetails = lessonAtLeafFactory;
  const sunlightConnectorState = getConnectorState(["sunlight"], unlockedSet, isRecap);
  const carbonConnectorState = getConnectorState(["carbon_dioxide"], unlockedSet, isRecap);
  const waterConnectorState = getConnectorState(["water"], unlockedSet, isRecap);
  const oxygenConnectorState = getConnectorState(["oxygen"], unlockedSet, isRecap);
  const sugarConnectorState = getConnectorState(["sugar"], unlockedSet, isRecap);
  const factoryConnectorState = showLeafZoomDetails
    ? getConnectorState(PHOTOSYNTHESIS_FACTORY_NODES, unlockedSet, isRecap)
    : "hidden";

  const renderPlantElement = (
    elementId: keyof typeof PHOTOSYNTHESIS_ELEMENTS,
    extraClassName = "",
  ) => {
    const element = PHOTOSYNTHESIS_ELEMENTS[elementId];
    const state = getPlantElementState(element.id, unlockedSet, isRecap);
    const active = state === "revealed" && highlightSet.has(element.id);
    const icon = state === "revealed" ? element.icon : "●";
    return (
      <div
        key={element.id}
        className={
          "concept-canvas__plant-element" +
          ` concept-canvas__plant-element--${state}` +
          ` concept-canvas__plant-element--${element.tone}` +
          (active ? " concept-canvas__plant-element--active" : "") +
          (extraClassName ? ` ${extraClassName}` : "")
        }
        data-plant-element-id={element.id}
        data-plant-element-state={state}
      >
        <span
          className={
            "concept-canvas__plant-icon" +
            (state === "hidden" ? " concept-canvas__plant-icon--hidden" : "")
          }
          aria-hidden="true"
        >
          {icon}
        </span>
        <span className="concept-canvas__plant-label">
          {state === "revealed" ? element.title : ""}
        </span>
        <span className="concept-canvas__plant-note">
          {state === "revealed" ? element.description : ""}
        </span>
      </div>
    );
  };

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
          className="concept-canvas__scene concept-canvas__scene--photosynthesis concept-canvas__scene--illustration concept-canvas__scene--flow"
          aria-label="Concept diagram"
        >
          <div className="concept-canvas__scene-header">
            <span className="concept-canvas__badge">Photosynthesis Process</span>
            <span className="concept-canvas__subhead">
              {isRecap
                ? "Read the whole story: sunlight, water, and carbon dioxide enter the plant; glucose and oxygen come out."
                : "Watch the ingredients move through the plant, zoom into the leaf factory, and follow the outputs back out."}
            </span>
          </div>
          <div
            className={
              "concept-canvas__bio-diagram" +
              (showLeafZoomDetails ? " concept-canvas__bio-diagram--factory-open" : "")
            }
          >
            <svg
              className="concept-canvas__diagram-arrows"
              viewBox="0 0 100 100"
              preserveAspectRatio="none"
              aria-hidden="true"
            >
              <defs>
                <marker
                  id="photosynthesisArrow"
                  viewBox="0 0 10 10"
                  refX="9"
                  refY="5"
                  markerWidth="5"
                  markerHeight="5"
                  orient="auto-start-reverse"
                >
                  <path d="M 0 0 L 10 5 L 0 10 z" fill="currentColor" />
                </marker>
              </defs>
              <path
                d="M18 16 C 28 18, 36 21, 44 28"
                className={`concept-canvas__diagram-arrow concept-canvas__diagram-arrow--${sunlightConnectorState}`}
              />
              <path
                d="M18 39 C 28 38, 36 37, 44 36"
                className={`concept-canvas__diagram-arrow concept-canvas__diagram-arrow--${carbonConnectorState}`}
              />
              <path
                d="M22 77 C 31 74, 38 69, 45 60"
                className={`concept-canvas__diagram-arrow concept-canvas__diagram-arrow--${waterConnectorState}`}
              />
              <path
                d="M56 29 C 66 24, 74 18, 82 18"
                className={`concept-canvas__diagram-arrow concept-canvas__diagram-arrow--${oxygenConnectorState}`}
              />
              <path
                d="M56 52 C 66 58, 74 66, 82 74"
                className={`concept-canvas__diagram-arrow concept-canvas__diagram-arrow--${sugarConnectorState}`}
              />
              <path
                d="M55 40 C 64 34, 72 29, 80 24"
                className={`concept-canvas__diagram-arrow concept-canvas__diagram-arrow--${factoryConnectorState}`}
              />
            </svg>

            <div
              className={
                "concept-canvas__plant-illustration" +
                (showLeafZoomDetails ? " concept-canvas__plant-illustration--factory-open" : "")
              }
            >
              <div className="concept-canvas__plant-sun-glow" aria-hidden="true" />
              <PhotosynthesisPlantGraphic highlightLeafFactory={leafFactoryActive} />
              <div className="concept-canvas__plant-stage-label">
                Plant body
              </div>
            </div>

            {PHOTOSYNTHESIS_OUTER_NODES.map((node) => (
              <div key={node.id} className={`concept-canvas__diagram-node ${node.className}`}>
                {renderPlantElement(node.id, "concept-canvas__plant-element--diagram")}
              </div>
            ))}

            {showLeafZoomDetails ? (
              <div
                className="concept-canvas__leaf-zoom concept-canvas__leaf-zoom--expanded"
                data-leaf-zoom-state="expanded"
              >
                <div className="concept-canvas__leaf-zoom-header">
                  <span className="concept-canvas__leaf-zoom-title">Inside the leaf</span>
                  <span className="concept-canvas__leaf-zoom-copy">This is the food-making factory.</span>
                </div>
                <div className="concept-canvas__leaf-zoom-grid">
                  {PHOTOSYNTHESIS_FACTORY_NODES.map((elementId) => (
                    <div key={elementId} className="concept-canvas__leaf-zoom-cell">
                      {renderPlantElement(elementId, "concept-canvas__plant-element--factory")}
                    </div>
                  ))}
                </div>
                <div className="concept-canvas__equation-ribbon">
                  {[...PHOTOSYNTHESIS_INPUTS, "arrow", ...PHOTOSYNTHESIS_OUTPUTS].map((token) => {
                    if (token === "arrow") {
                      return (
                        <span key={token} className="concept-canvas__equation-arrow" aria-hidden="true">
                          →
                        </span>
                      );
                    }
                    const elementId = token as keyof typeof PHOTOSYNTHESIS_ELEMENTS;
                    const revealed = isRecap || unlockedSet.has(elementId);
                    return (
                      <span
                        key={elementId}
                        className={
                          "concept-canvas__equation-token" +
                          (revealed ? " concept-canvas__equation-token--revealed" : "")
                        }
                        aria-label={revealed ? PHOTOSYNTHESIS_ELEMENTS[elementId].title : "Hidden clue"}
                      >
                        {revealed ? PHOTOSYNTHESIS_ELEMENTS[elementId].title : "•"}
                      </span>
                    );
                  })}
                </div>
              </div>
            ) : null}
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
