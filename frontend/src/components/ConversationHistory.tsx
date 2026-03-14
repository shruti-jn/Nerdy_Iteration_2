import { useEffect, useRef } from "react";
import type { ConversationEntry } from "../types";
import "./ConversationHistory.css";

interface Props {
  history: ConversationEntry[];
}

export function ConversationHistory({ history }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [history.length]);

  return (
    <aside className="conv-history">
      <div className="conv-history__header">
        <span className="conv-history__title">Conversation</span>
        <span className="conv-history__count">{history.length}</span>
      </div>

      <div className="conv-history__scroll">
        {history.length === 0 && (
          <div className="conv-history__empty">
            <span className="conv-history__empty-icon">💬</span>
            <p>Your conversation will appear here.</p>
          </div>
        )}

        {history.map((entry) => (
          <div
            key={entry.id}
            className={`conv-entry conv-entry--${entry.role}`}
            style={{ animationDelay: "0ms" }}
          >
            <div className="conv-entry__role">
              {entry.role === "student" ? "You" : "Nerdy"}
            </div>
            <div className="conv-entry__text">{entry.text}</div>
          </div>
        ))}

        <div ref={bottomRef} />
      </div>
    </aside>
  );
}
