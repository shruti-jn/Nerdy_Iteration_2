import type { TopicId, TopicInfo } from "../types";
import "./TopicSelectView.css";

interface Props {
  onSelectTopic: (id: TopicId, displayName: string) => void;
}

const TOPICS: TopicInfo[] = [
  { id: "photosynthesis", label: "Photosynthesis", description: "How do plants make food from sunlight?", icon: "\u{1F331}", available: true },
  { id: "newtons_laws", label: "Newton's Laws", description: "Why do objects move the way they do?", icon: "\u{1F680}", available: true },
  { id: "water_cycle", label: "Water Cycle", description: "Where does rain come from and where does it go?", icon: "\u{1F4A7}", available: false },
  { id: "fractions", label: "Fractions", description: "How do we split things into equal parts?", icon: "\u{1F522}", available: false },
  { id: "solar_system", label: "Solar System", description: "What's out there beyond our sky?", icon: "\u{1FA90}", available: false },
  { id: "volcanoes", label: "Volcanoes", description: "What makes mountains explode with lava?", icon: "\u{1F30B}", available: false },
];

export function TopicSelectView({ onSelectTopic }: Props) {
  return (
    <div className="topic-select">
      <div className="topic-select__content">
        {/* Brand */}
        <div className="topic-select__brand">
          <span className="topic-select__logo">N</span>
          <span className="topic-select__name">Nerdy</span>
        </div>

        {/* Heading */}
        <h1 className="topic-select__heading">What do you want to learn today?</h1>
        <div className="topic-select__subheading">
          <span className="topic-select__grade-badge">Grade 8</span>
          <span className="topic-select__dot">&middot;</span>
          <span className="topic-select__subject">Science</span>
        </div>

        {/* Topic Grid */}
        <div className="topic-select__grid">
          {TOPICS.map((t) => (
            <button
              key={t.id}
              className={`topic-card ${t.available ? "topic-card--active" : "topic-card--disabled"}`}
              onClick={() => t.available && onSelectTopic(t.id as TopicId, t.label)}
              disabled={!t.available}
              aria-label={t.available ? `Start ${t.label}` : `${t.label} — coming soon`}
            >
              <span className="topic-card__icon">{t.icon}</span>
              <span className="topic-card__label">{t.label}</span>
              <span className="topic-card__desc">{t.description}</span>
              {!t.available && <span className="topic-card__badge">Coming Soon</span>}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
