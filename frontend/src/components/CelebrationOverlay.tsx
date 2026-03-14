import { useMemo } from "react";
import "./CelebrationOverlay.css";

interface Props {
  topic: string;
  turnCount: number;
  totalTurns: number;
  onTryAnother: () => void;
}

/** Confetti colors — teal/blue/purple palette matching the app theme. */
const CONFETTI_COLORS = [
  "#2dd4bf", // teal (accent)
  "#3b82f6", // blue
  "#a78bfa", // purple
  "#f472b6", // pink
  "#fbbf24", // amber
  "#34d399", // emerald
];

/** Number of confetti particles to generate. */
const PARTICLE_COUNT = 40;

/**
 * Full-screen celebration overlay shown when all turns are complete.
 *
 * Features a CSS-only confetti burst, a congratulatory message with the
 * topic name, session stats, and a CTA to explore another topic.
 */
export function CelebrationOverlay({ topic, turnCount, totalTurns, onTryAnother }: Props) {
  const particles = useMemo(() => generateParticles(PARTICLE_COUNT), []);

  return (
    <div className="celebration" role="dialog" aria-labelledby="celebration-title">
      <div className="celebration__card">
        {/* Confetti burst */}
        <div className="celebration__confetti" aria-hidden="true">
          {particles.map((p) => (
            <div
              key={p.id}
              className="celebration__particle"
              style={{
                left: `${p.x}%`,
                top: "-10px",
                width: `${p.size}px`,
                height: `${p.size * p.aspect}px`,
                background: p.color,
                animationDuration: `${p.duration}s`,
                animationDelay: `${p.delay}s`,
                borderRadius: p.round ? "50%" : "2px",
              }}
            />
          ))}
        </div>

        <span className="celebration__icon" aria-hidden="true">
          🎉
        </span>

        <h2 className="celebration__title" id="celebration-title">
          Amazing work!
        </h2>

        <p className="celebration__subtitle">
          You just completed a full Socratic session on{" "}
          <span className="celebration__topic">{topic}</span>. Keep that
          curiosity going!
        </p>

        <div className="celebration__stats">
          <div className="celebration__stat">
            <span className="celebration__stat-value">{turnCount}</span>
            <span className="celebration__stat-label">Questions</span>
          </div>
          <div className="celebration__stat">
            <span className="celebration__stat-value">{totalTurns}</span>
            <span className="celebration__stat-label">Total turns</span>
          </div>
        </div>

        <button className="celebration__cta" onClick={onTryAnother} autoFocus>
          Try another topic
        </button>
      </div>
    </div>
  );
}

/* ── Particle generation (deterministic per mount) ────────────────────── */

interface Particle {
  id: number;
  x: number;
  size: number;
  aspect: number;
  round: boolean;
  color: string;
  duration: number;
  delay: number;
}

function generateParticles(count: number): Particle[] {
  const particles: Particle[] = [];
  for (let i = 0; i < count; i++) {
    particles.push({
      id: i,
      x: (i / count) * 100 + (seededRandom(i) * 20 - 10),
      size: 6 + seededRandom(i + 100) * 6,
      aspect: 0.6 + seededRandom(i + 200) * 1.4,
      round: seededRandom(i + 300) > 0.5,
      color: CONFETTI_COLORS[i % CONFETTI_COLORS.length],
      duration: 2 + seededRandom(i + 400) * 2,
      delay: 0.3 + seededRandom(i + 500) * 1.2,
    });
  }
  return particles;
}

/** Simple seeded pseudo-random for deterministic confetti layout. */
function seededRandom(seed: number): number {
  const x = Math.sin(seed * 9301 + 49297) * 233280;
  return x - Math.floor(x);
}
