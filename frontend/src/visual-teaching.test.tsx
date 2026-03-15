/**
 * Tests for visual teaching feature.
 *
 * Covers:
 * - useSessionStore visual state management (setVisual, reset, restoreSession, bargeIn)
 * - StepProgress component rendering (dots, filled state, active state, recap)
 * - ConceptCanvas component rendering (emoji diagram, caption, recap checkmark)
 * - TeachingPanel composite component (title switching, backward compat, live badge, waveform)
 */
import { describe, it, expect, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { renderHook, act } from "@testing-library/react";
import { useSessionStore } from "./useSessionStore";
import { TeachingPanel } from "./components/TeachingPanel";
import { ConceptCanvas } from "./components/ConceptCanvas";
import { StepProgress } from "./components/StepProgress";
import type { LessonVisualState } from "./types";

// ── Mock data ───────────────────────────────────────────────────────────────

const MOCK_VISUAL: LessonVisualState = {
  diagramId: "photosynthesis",
  stepId: 2,
  stepLabel: "The Green Kitchen",
  totalSteps: 7,
  highlightKeys: ["chloroplast", "chlorophyll"],
  caption: "Chloroplasts are tiny kitchens inside every leaf",
  emojiDiagram: "🌿 → 🏭 Chloroplast → 👨‍🍳 Chlorophyll",
  turnNumber: 3,
  isRecap: false,
};

const MOCK_RECAP_VISUAL: LessonVisualState = {
  ...MOCK_VISUAL,
  stepId: -1,
  stepLabel: "Complete!",
  isRecap: true,
  emojiDiagram: "🌱 ☀️+💧+CO₂ → 🏭 → 🍬 + 💨 O₂ → 🌍🫁🍎",
  caption: "You traced the full journey of photosynthesis!",
};

// ── 1. Store tests ──────────────────────────────────────────────────────────

describe("useSessionStore — visual state", () => {
  beforeEach(() => {
    // Reset the hook state between tests by rendering a fresh hook
    // (each renderHook creates its own React tree)
  });

  it("visual is null by default", () => {
    const { result } = renderHook(() => useSessionStore());
    expect(result.current.visual).toBeNull();
  });

  it("setVisual updates visual state", () => {
    const { result } = renderHook(() => useSessionStore());

    act(() => {
      result.current.setVisual(MOCK_VISUAL);
    });

    expect(result.current.visual).toEqual(MOCK_VISUAL);
  });

  it("reset() clears visual to null", () => {
    const { result } = renderHook(() => useSessionStore());

    act(() => {
      result.current.setVisual(MOCK_VISUAL);
    });
    expect(result.current.visual).toEqual(MOCK_VISUAL);

    act(() => {
      result.current.reset();
    });
    expect(result.current.visual).toBeNull();
  });

  it("restoreSession() clears visual to null", () => {
    const { result } = renderHook(() => useSessionStore());

    act(() => {
      result.current.setVisual(MOCK_VISUAL);
    });
    expect(result.current.visual).toEqual(MOCK_VISUAL);

    act(() => {
      result.current.restoreSession([], 3, 15);
    });
    expect(result.current.visual).toBeNull();
  });

  it("bargeIn() preserves visual", () => {
    const { result } = renderHook(() => useSessionStore());

    act(() => {
      result.current.setVisual(MOCK_VISUAL);
      result.current.startTutorResponse();
    });
    act(() => {
      result.current.appendStreamWord("hi");
    });
    act(() => {
      result.current.bargeIn();
    });

    expect(result.current.visual).toEqual(MOCK_VISUAL);
  });
});

// ── 2. StepProgress component tests ─────────────────────────────────────────

describe("StepProgress", () => {
  it("renders correct number of dots", () => {
    render(
      <StepProgress currentStep={2} totalSteps={7} stepLabel="The Green Kitchen" isRecap={false} />,
    );

    const dots = screen.getAllByLabelText(/^Step \d+/);
    expect(dots).toHaveLength(7);
  });

  it("fills dots up to and including currentStep", () => {
    render(
      <StepProgress currentStep={2} totalSteps={7} stepLabel="The Green Kitchen" isRecap={false} />,
    );

    const dots = screen.getAllByLabelText(/^Step \d+/);
    // Dots 0, 1, 2 (Steps 1, 2, 3) should be filled
    for (let i = 0; i <= 2; i++) {
      expect(dots[i].className).toContain("step-progress__dot--filled");
    }
    // Dots 3-6 (Steps 4-7) should NOT be filled
    for (let i = 3; i < 7; i++) {
      expect(dots[i].className).not.toContain("step-progress__dot--filled");
    }
  });

  it("marks currentStep as active", () => {
    render(
      <StepProgress currentStep={2} totalSteps={7} stepLabel="The Green Kitchen" isRecap={false} />,
    );

    const dots = screen.getAllByLabelText(/^Step \d+/);
    // Only dot at index 2 should have active class
    expect(dots[2].className).toContain("step-progress__dot--active");
    // Others should not
    for (let i = 0; i < 7; i++) {
      if (i !== 2) {
        expect(dots[i].className).not.toContain("step-progress__dot--active");
      }
    }
  });

  it("shows step label", () => {
    render(
      <StepProgress currentStep={2} totalSteps={7} stepLabel="The Green Kitchen" isRecap={false} />,
    );

    expect(screen.getByText("The Green Kitchen")).toBeInTheDocument();
  });

  it("shows 'Complete!' on recap", () => {
    render(
      <StepProgress currentStep={-1} totalSteps={7} stepLabel="Ignored Label" isRecap={true} />,
    );

    expect(screen.getByText("Complete!")).toBeInTheDocument();
    expect(screen.queryByText("Ignored Label")).not.toBeInTheDocument();
  });

  it("fills all dots on recap", () => {
    render(
      <StepProgress currentStep={-1} totalSteps={7} stepLabel="Complete!" isRecap={true} />,
    );

    const dots = screen.getAllByLabelText(/^Step \d+/);
    for (const dot of dots) {
      expect(dot.className).toContain("step-progress__dot--filled");
    }
  });
});

// ── 3. ConceptCanvas component tests ────────────────────────────────────────

describe("ConceptCanvas", () => {
  it("renders a layered scene when the topic is known", () => {
    render(
      <ConceptCanvas
        diagramId={MOCK_VISUAL.diagramId}
        stepId={MOCK_VISUAL.stepId}
        emojiDiagram={MOCK_VISUAL.emojiDiagram}
        caption={MOCK_VISUAL.caption}
        isRecap={false}
      />,
    );

    expect(screen.getByText("Greenhouse Map")).toBeInTheDocument();
    expect(screen.getByText("Leaf lab")).toBeInTheDocument();
  });

  it("renders caption when provided", () => {
    render(
      <ConceptCanvas
        diagramId={MOCK_VISUAL.diagramId}
        stepId={MOCK_VISUAL.stepId}
        emojiDiagram={MOCK_VISUAL.emojiDiagram}
        caption="Chloroplasts are tiny kitchens inside every leaf"
        isRecap={false}
      />,
    );

    expect(
      screen.getByText("Chloroplasts are tiny kitchens inside every leaf"),
    ).toBeInTheDocument();
  });

  it("does not render caption when null", () => {
    const { container } = render(
      <ConceptCanvas
        diagramId={MOCK_VISUAL.diagramId}
        stepId={MOCK_VISUAL.stepId}
        emojiDiagram={MOCK_VISUAL.emojiDiagram}
        caption={null}
        isRecap={false}
      />,
    );

    expect(container.querySelector(".concept-canvas__caption")).toBeNull();
  });

  it("marks past, current, and future layers with reveal statuses", () => {
    const { container } = render(
      <ConceptCanvas
        diagramId={MOCK_VISUAL.diagramId}
        stepId={MOCK_VISUAL.stepId}
        emojiDiagram={MOCK_VISUAL.emojiDiagram}
        caption={MOCK_VISUAL.caption}
        isRecap={false}
      />,
    );

    expect(
      container.querySelector('[data-layer-id="seed-tree"]')?.getAttribute("data-layer-status"),
    ).toBe("mastered");
    expect(
      container.querySelector('[data-layer-id="leaf-lab"]')?.getAttribute("data-layer-status"),
    ).toBe("revealed");
    expect(
      container.querySelector('[data-layer-id="products"]')?.getAttribute("data-layer-status"),
    ).toBe("hidden");
    expect(screen.getAllByText("Locked").length).toBeGreaterThan(0);
  });

  it("shows checkmark on recap", () => {
    const { container } = render(
      <ConceptCanvas
        diagramId={MOCK_RECAP_VISUAL.diagramId}
        stepId={MOCK_RECAP_VISUAL.stepId}
        emojiDiagram={MOCK_RECAP_VISUAL.emojiDiagram}
        caption={MOCK_RECAP_VISUAL.caption}
        isRecap={true}
      />,
    );

    expect(screen.getByLabelText("Complete")).toBeInTheDocument();
    expect(screen.getByText("✓")).toBeInTheDocument();
    const layers = Array.from(container.querySelectorAll("[data-layer-status]"));
    expect(layers.every((layer) => layer.getAttribute("data-layer-status") === "mastered")).toBe(true);
  });

  it("does not show checkmark when not recap", () => {
    render(
      <ConceptCanvas
        diagramId={MOCK_VISUAL.diagramId}
        stepId={MOCK_VISUAL.stepId}
        emojiDiagram={MOCK_VISUAL.emojiDiagram}
        caption={MOCK_VISUAL.caption}
        isRecap={false}
      />,
    );

    expect(screen.queryByLabelText("Complete")).not.toBeInTheDocument();
    expect(screen.queryByText("✓")).not.toBeInTheDocument();
  });

  it("falls back to the raw emoji diagram for unknown topics", () => {
    render(
      <ConceptCanvas
        diagramId="unknown-topic"
        stepId={1}
        emojiDiagram="⭐ → ❓"
        caption="Fallback"
        isRecap={false}
      />,
    );

    expect(screen.getByText("⭐ → ❓")).toBeInTheDocument();
  });
});

// ── 4. TeachingPanel component tests ────────────────────────────────────────

describe("TeachingPanel", () => {
  it("shows 'Tutor Response' title when visual is null", () => {
    render(<TeachingPanel mode="idle" streamingWords={[]} visual={null} />);

    expect(screen.getByText("Tutor Response")).toBeInTheDocument();
  });

  it("shows 'Concept Map' title when visual is set", () => {
    render(<TeachingPanel mode="idle" streamingWords={[]} visual={MOCK_VISUAL} />);

    expect(screen.getByText("Concept Map")).toBeInTheDocument();
    expect(screen.queryByText("Tutor Response")).not.toBeInTheDocument();
  });

  it("renders tutor text when visual is null (backward compat)", () => {
    render(
      <TeachingPanel mode="tutor-responding" streamingWords={["hello", "world"]} visual={null} />,
    );

    expect(screen.getByText("hello")).toBeInTheDocument();
    expect(screen.getByText("world")).toBeInTheDocument();
  });

  it("renders both visual and tutor text when visual is set", () => {
    render(
      <TeachingPanel mode="tutor-responding" streamingWords={["hello"]} visual={MOCK_VISUAL} />,
    );

    // Visual content
    expect(screen.getByText("Greenhouse Map")).toBeInTheDocument();
    expect(screen.getByText("Leaf lab")).toBeInTheDocument();
    // Tutor text
    expect(screen.getByText("hello")).toBeInTheDocument();
  });

  it("shows empty state when no words and not speaking", () => {
    render(<TeachingPanel mode="idle" streamingWords={[]} visual={null} />);

    expect(
      screen.getByText("The tutor's response will appear here as they speak."),
    ).toBeInTheDocument();
  });

  it("shows live badge when tutor is responding", () => {
    render(<TeachingPanel mode="tutor-responding" streamingWords={[]} visual={null} />);

    expect(screen.getByText("Live")).toBeInTheDocument();
  });

  it("shows waveform when tutor is speaking", () => {
    render(<TeachingPanel mode="tutor-responding" streamingWords={[]} visual={null} />);

    expect(screen.getByLabelText("Audio waveform")).toBeInTheDocument();
  });
});
