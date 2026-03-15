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

const SCENES: Partial<Record<TopicId, ConceptSceneDefinition>> = {
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
  if (diagramId === "newtons_laws") {
    return SCENES[diagramId] ?? null;
  }
  return null;
}
