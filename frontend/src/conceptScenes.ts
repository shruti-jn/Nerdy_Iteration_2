import type { TopicId } from "./types";

export type ConceptLayerTone = "mint" | "sun" | "sky" | "amber" | "earth" | "slate";

export interface ConceptSceneLayer {
  id: string;
  stepId: number;
  title: string;
  icon: string;
  x: number;
  y: number;
  tone: ConceptLayerTone;
}

export interface ConceptSceneDefinition {
  id: TopicId;
  badge: string;
  subhead: string;
  layers: ConceptSceneLayer[];
}

const SCENES: Record<TopicId, ConceptSceneDefinition> = {
  photosynthesis: {
    id: "photosynthesis",
    badge: "Greenhouse Map",
    subhead: "A living scene fills in as each idea clicks into place.",
    layers: [
      { id: "seed-tree", stepId: 0, title: "Seed to tree", icon: "🌱🌳", x: 18, y: 26, tone: "earth" },
      { id: "ingredients", stepId: 1, title: "Sun + water + CO2", icon: "☀️💧🌬️", x: 74, y: 20, tone: "sun" },
      { id: "leaf-lab", stepId: 2, title: "Leaf lab", icon: "🍃🔬", x: 68, y: 48, tone: "mint" },
      { id: "light-power", stepId: 3, title: "Light power", icon: "☀️⚡", x: 30, y: 48, tone: "sky" },
      { id: "products", stepId: 4, title: "Glucose + oxygen", icon: "🍬💨", x: 68, y: 76, tone: "amber" },
      { id: "payoff", stepId: 5, title: "Why it matters", icon: "🌍🫁🍎", x: 24, y: 78, tone: "sky" },
      { id: "teach-back", stepId: 6, title: "You explain it", icon: "🎓", x: 50, y: 24, tone: "mint" },
    ],
  },
  newtons_laws: {
    id: "newtons_laws",
    badge: "Motion Map",
    subhead: "Each unlocked force adds another moving part to the scene.",
    layers: [
      { id: "car-stop", stepId: 0, title: "Car stop mystery", icon: "🚗🛑", x: 18, y: 22, tone: "amber" },
      { id: "moving-object", stepId: 1, title: "Objects in motion", icon: "🏒💨", x: 74, y: 20, tone: "sky" },
      { id: "friction", stepId: 2, title: "Friction", icon: "🟫✋", x: 72, y: 48, tone: "earth" },
      { id: "rest", stepId: 3, title: "Objects at rest", icon: "📘🪑", x: 24, y: 52, tone: "slate" },
      { id: "inertia", stepId: 4, title: "Inertia", icon: "🧠➡️", x: 48, y: 28, tone: "mint" },
      { id: "force-mass", stepId: 5, title: "Force vs mass", icon: "🛒🧱", x: 26, y: 78, tone: "amber" },
      { id: "formula", stepId: 6, title: "F = ma", icon: "⚡📏", x: 70, y: 78, tone: "sky" },
      { id: "teach-back", stepId: 7, title: "You explain it", icon: "🎓", x: 50, y: 54, tone: "mint" },
    ],
  },
};

export function getConceptScene(diagramId: string): ConceptSceneDefinition | null {
  if (diagramId === "photosynthesis" || diagramId === "newtons_laws") {
    return SCENES[diagramId];
  }
  return null;
}
