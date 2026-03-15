import { useEffect, useRef, useState } from "react";
import "./ConceptCanvas.css";

interface Props {
  emojiDiagram: string;
  caption: string | null;
  isRecap: boolean;
}

export function ConceptCanvas({ emojiDiagram, caption, isRecap }: Props) {
  const [visible, setVisible] = useState(true);
  const prevDiagramRef = useRef(emojiDiagram);

  useEffect(() => {
    if (prevDiagramRef.current === emojiDiagram) return;
    prevDiagramRef.current = emojiDiagram;
    setVisible(false);
    const id = setTimeout(() => setVisible(true), 180);
    return () => clearTimeout(id);
  }, [emojiDiagram]);

  return (
    <div
      className={
        "concept-canvas" +
        (isRecap ? " concept-canvas--recap" : "") +
        (visible ? " concept-canvas--visible" : " concept-canvas--hidden")
      }
    >
      <div className="concept-canvas__diagram" aria-label="Concept diagram">
        {emojiDiagram}
      </div>
      {caption && (
        <p className="concept-canvas__caption">{caption}</p>
      )}
      {isRecap && (
        <span className="concept-canvas__check" aria-label="Complete">✓</span>
      )}
    </div>
  );
}
