import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { App } from "./App";
import { LatencyPanel } from "./components/LatencyPanel";
import { LatencyTrend } from "./components/LatencyTrend";
import { ConversationHistory } from "./components/ConversationHistory";
import { AvatarFeed } from "./components/AvatarFeed";
import { TutorResponse } from "./components/TutorResponse";
import { BottomBar } from "./components/BottomBar";
import { TopicSelectView } from "./components/TopicSelectView";
import { GettingReadyView } from "./components/GettingReadyView";
import { CelebrationOverlay } from "./components/CelebrationOverlay";
import { useSessionStore } from "./useSessionStore";
import { renderHook, act as hookAct } from "@testing-library/react";

// ═══════════════════════════════════════════════════════════════════════════════
// T4-01: App initial render — starts on TopicSelectView
// ═══════════════════════════════════════════════════════════════════════════════
describe("T4-01: App renders (topic-select view)", () => {
  it("renders the topic selection heading", () => {
    render(<App />);
    expect(screen.getByText("What do you want to learn today?")).toBeInTheDocument();
  });

  it("renders the Socrates VI brand on topic select view", () => {
    render(<App />);
    expect(screen.getByText("Socrates VI")).toBeInTheDocument();
  });

  it("shows Grade 8 badge on topic select", () => {
    render(<App />);
    expect(screen.getByText("Grade 8")).toBeInTheDocument();
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// T4-02: TopicSelectView renders topic cards (replaces three-column layout test)
// ═══════════════════════════════════════════════════════════════════════════════
describe("T4-02: TopicSelectView topic cards", () => {
  it("renders all six topic cards", () => {
    const onSelect = vi.fn();
    render(<TopicSelectView onSelectTopic={onSelect} />);
    expect(screen.getByText("Photosynthesis")).toBeInTheDocument();
    expect(screen.getByText("Newton's Laws")).toBeInTheDocument();
    expect(screen.getByText("Water Cycle")).toBeInTheDocument();
    expect(screen.getByText("Fractions")).toBeInTheDocument();
    expect(screen.getByText("Solar System")).toBeInTheDocument();
    expect(screen.getByText("Volcanoes")).toBeInTheDocument();
  });

  it("marks coming-soon cards as disabled", () => {
    const onSelect = vi.fn();
    render(<TopicSelectView onSelectTopic={onSelect} />);
    const badges = screen.getAllByText("Coming Soon");
    // 4 topics are unavailable: Water Cycle, Fractions, Solar System, Volcanoes
    expect(badges).toHaveLength(4);
  });

  it("disabled cards cannot be clicked", () => {
    const onSelect = vi.fn();
    render(<TopicSelectView onSelectTopic={onSelect} />);
    const waterCycleBtn = screen.getByRole("button", { name: /Water Cycle — coming soon/i });
    expect(waterCycleBtn).toBeDisabled();
    fireEvent.click(waterCycleBtn);
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("clicking an active topic fires callback with id and label", () => {
    const onSelect = vi.fn();
    render(<TopicSelectView onSelectTopic={onSelect} />);
    const photoBtn = screen.getByRole("button", { name: /Start Photosynthesis/i });
    expect(photoBtn).not.toBeDisabled();
    fireEvent.click(photoBtn);
    expect(onSelect).toHaveBeenCalledWith("photosynthesis", "Photosynthesis");
  });

  it("clicking Newton's Laws fires callback correctly", () => {
    const onSelect = vi.fn();
    render(<TopicSelectView onSelectTopic={onSelect} />);
    const newtonBtn = screen.getByRole("button", { name: /Start Newton's Laws/i });
    fireEvent.click(newtonBtn);
    expect(onSelect).toHaveBeenCalledWith("newtons_laws", "Newton's Laws");
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// T4-03: BottomBar mic/barge-in in different modes (tested via component directly)
// ═══════════════════════════════════════════════════════════════════════════════
describe("T4-03: BottomBar mic button states", () => {
  const noop = () => {};

  it("shows hold-to-speak hint in idle mode", () => {
    render(
      <BottomBar mode="idle" latencyMs={null} onMicPress={noop} onMicRelease={noop} onBargeIn={noop} />
    );
    expect(screen.getByText("Hold to speak")).toBeInTheDocument();
  });

  it("mic button has correct aria-label in idle", () => {
    render(
      <BottomBar mode="idle" latencyMs={null} onMicPress={noop} onMicRelease={noop} onBargeIn={noop} />
    );
    expect(screen.getByRole("button", { name: /hold to speak/i })).toBeInTheDocument();
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// T4-04: Barge-in button tested via BottomBar component
// ═══════════════════════════════════════════════════════════════════════════════
describe("T4-04: Barge-in button", () => {
  const noop = () => {};

  it("interrupt button is disabled in idle mode", () => {
    render(
      <BottomBar mode="idle" latencyMs={null} onMicPress={noop} onMicRelease={noop} onBargeIn={noop} />
    );
    const bargeBtn = screen.getByRole("button", { name: /interrupt/i });
    expect(bargeBtn).toBeDisabled();
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// T4-05: TopicSelectView displays Science subject label
// ═══════════════════════════════════════════════════════════════════════════════
describe("T4-05: TopicSelectView metadata", () => {
  it("shows Grade 8 and Science labels", () => {
    const onSelect = vi.fn();
    render(<TopicSelectView onSelectTopic={onSelect} />);
    expect(screen.getByText("Grade 8")).toBeInTheDocument();
    expect(screen.getByText("Science")).toBeInTheDocument();
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// T4-06: ConversationHistory renders entries
// ═══════════════════════════════════════════════════════════════════════════════
describe("T4-06: ConversationHistory renders entries", () => {
  it("shows empty state when no history", () => {
    render(<ConversationHistory history={[]} />);
    expect(screen.getByText(/conversation will appear/i)).toBeInTheDocument();
  });

  it("renders student entry with correct role label", () => {
    render(
      <ConversationHistory
        history={[{ id: "1", role: "student", text: "What is ATP?", timestamp: 0 }]}
      />
    );
    expect(screen.getByText("You")).toBeInTheDocument();
    expect(screen.getByText("What is ATP?")).toBeInTheDocument();
  });

  it("renders tutor entry with Socrates VI label", () => {
    render(
      <ConversationHistory
        history={[{ id: "2", role: "tutor", text: "What do you think ATP does?", timestamp: 0 }]}
      />
    );
    expect(screen.getByText("Socrates VI")).toBeInTheDocument();
  });
});

describe("T4-06B: GettingReadyView resume actions", () => {
  const noop = () => {};

  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows both Start Lesson and Continue Lesson when a session can be resumed", () => {
    render(
      <GettingReadyView
        topic="Photosynthesis"
        avatarState="live"
        wsConnected={true}
        canContinue={true}
        videoRef={{ current: null }}
        onBack={noop}
        onStart={noop}
        onContinue={noop}
      />
    );

    expect(screen.getByRole("button", { name: "Start Lesson" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Continue Lesson" })).toBeInTheDocument();
  });

  it("shows only Start Lesson for a brand-new session", () => {
    render(
      <GettingReadyView
        topic="Photosynthesis"
        avatarState="live"
        wsConnected={true}
        canContinue={false}
        videoRef={{ current: null }}
        onBack={noop}
        onStart={noop}
        onContinue={noop}
      />
    );

    expect(screen.getByRole("button", { name: "Start Lesson" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Continue Lesson" })).not.toBeInTheDocument();
  });

  it("keeps Start Lesson and Continue Lesson disabled until the avatar is live", () => {
    render(
      <GettingReadyView
        topic="Photosynthesis"
        avatarState="connecting"
        wsConnected={true}
        canContinue={true}
        videoRef={{ current: null }}
        onBack={noop}
        onStart={noop}
        onContinue={noop}
      />
    );

    const startBtn = screen.getByRole("button", { name: "Start Lesson" });
    const continueBtn = screen.getByRole("button", { name: "Continue Lesson" });

    expect(startBtn).toBeDisabled();
    expect(continueBtn).toBeDisabled();

    hookAct(() => {
      vi.advanceTimersByTime(10_000);
    });

    expect(screen.getByRole("button", { name: "Start without avatar" })).toBeInTheDocument();
    expect(startBtn).toBeDisabled();
    expect(continueBtn).toBeDisabled();
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// T4-07: AvatarFeed shows correct status badge per mode
// ═══════════════════════════════════════════════════════════════════════════════
describe("T4-07: AvatarFeed status badges", () => {
  it("shows Ready badge in idle mode when avatar is live", () => {
    render(<AvatarFeed mode="idle" avatarState="live" />);
    expect(screen.getByText("Ready")).toBeInTheDocument();
  });

  it("shows Connecting badge in idle mode when avatar is connecting", () => {
    render(<AvatarFeed mode="idle" avatarState="connecting" />);
    expect(screen.getByText("Connecting")).toBeInTheDocument();
  });

  it("shows Connecting badge in idle mode when avatar is slow", () => {
    render(<AvatarFeed mode="idle" avatarState="slow" />);
    expect(screen.getByText("Connecting")).toBeInTheDocument();
  });

  it("shows Listening badge in student-speaking mode", () => {
    render(<AvatarFeed mode="student-speaking" avatarState="live" />);
    expect(screen.getByText("Listening…")).toBeInTheDocument();
  });

  it("shows Responding badge in tutor-responding mode", () => {
    render(<AvatarFeed mode="tutor-responding" avatarState="live" />);
    expect(screen.getByText("Responding")).toBeInTheDocument();
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// T4-14: AvatarFeed avatar connection states
// ═══════════════════════════════════════════════════════════════════════════════
describe("T4-14: AvatarFeed avatar connection states", () => {
  it("shows 'Setting up your session' when connecting", () => {
    render(<AvatarFeed mode="idle" avatarState="connecting" />);
    expect(screen.getByText(/Setting up your session/)).toBeInTheDocument();
    expect(screen.queryByText(/almost ready/)).not.toBeInTheDocument();
  });

  it("shows 'Your tutor is almost ready' when slow", () => {
    render(<AvatarFeed mode="idle" avatarState="slow" />);
    expect(screen.getByText(/Your tutor is almost ready/)).toBeInTheDocument();
    expect(screen.getByText(/few extra seconds/)).toBeInTheDocument();
  });

  it("does not show connecting/slow copy when live", () => {
    render(<AvatarFeed mode="idle" avatarState="live" />);
    expect(screen.queryByText(/Setting up your session/)).not.toBeInTheDocument();
    expect(screen.queryByText(/almost ready/)).not.toBeInTheDocument();
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// T4-15: AvatarFeed in tutor-greeting mode
// ═══════════════════════════════════════════════════════════════════════════════
describe("T4-15: AvatarFeed tutor-greeting mode", () => {
  it("applies speaking frame class in tutor-greeting mode", () => {
    const { container } = render(<AvatarFeed mode="tutor-greeting" avatarState="live" />);
    const frame = container.querySelector(".avatar-feed__frame--speaking");
    expect(frame).toBeInTheDocument();
  });

  it("does not show a badge for tutor-greeting (no explicit badge mapped)", () => {
    render(<AvatarFeed mode="tutor-greeting" avatarState="live" />);
    // The component only renders SpeakingBadge for tutor-responding,
    // not tutor-greeting. No badge text should appear.
    expect(screen.queryByText("Ready")).not.toBeInTheDocument();
    expect(screen.queryByText("Listening…")).not.toBeInTheDocument();
    // "Responding" badge only renders for tutor-responding
    expect(screen.queryByText("Responding")).not.toBeInTheDocument();
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// T4-08: TutorResponse streams words
// ═══════════════════════════════════════════════════════════════════════════════
describe("T4-08: TutorResponse word streaming", () => {
  it("shows empty state when no words and not responding", () => {
    render(<TutorResponse mode="idle" streamingWords={[]} />);
    expect(screen.getByText(/words will appear here/i)).toBeInTheDocument();
  });

  it("renders streaming words when tutor is responding", () => {
    render(<TutorResponse mode="tutor-responding" streamingWords={["What", "do", "you", "think?"]} />);
    expect(screen.getByText(/What/)).toBeInTheDocument();
    expect(screen.getByText(/think\?/)).toBeInTheDocument();
  });

  it("shows Live badge when tutor is responding", () => {
    render(<TutorResponse mode="tutor-responding" streamingWords={[]} />);
    expect(screen.getByText("Live")).toBeInTheDocument();
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// T4-09: useSessionStore state transitions
// ═══════════════════════════════════════════════════════════════════════════════
describe("T4-09: useSessionStore state transitions", () => {
  it("starts in idle mode", () => {
    const { result } = renderHook(() => useSessionStore());
    expect(result.current.mode).toBe("idle");
  });

  it("addStudentUtterance adds to history without changing mode", () => {
    const { result } = renderHook(() => useSessionStore());
    hookAct(() => {
      result.current.addStudentUtterance("Hello");
    });
    // addStudentUtterance does NOT change mode — the caller manages transitions
    expect(result.current.mode).toBe("idle");
    expect(result.current.history).toHaveLength(1);
    expect(result.current.history[0]?.role).toBe("student");
  });

  it("transitions to tutor-responding on startTutorResponse", () => {
    const { result } = renderHook(() => useSessionStore());
    hookAct(() => {
      result.current.startTutorResponse();
    });
    expect(result.current.mode).toBe("tutor-responding");
  });

  it("accumulates streaming words", () => {
    const { result } = renderHook(() => useSessionStore());
    hookAct(() => {
      result.current.startTutorResponse();
      result.current.appendStreamWord("What");
      result.current.appendStreamWord("is");
    });
    expect(result.current.streamingWords).toEqual(["What", "is"]);
  });

  it("commits tutor response to history and returns to idle", () => {
    const { result } = renderHook(() => useSessionStore());
    hookAct(() => {
      result.current.startTutorResponse();
      result.current.appendStreamWord("Why");
      result.current.appendStreamWord("do");
      result.current.appendStreamWord("you");
      result.current.appendStreamWord("think?");
      result.current.commitTutorResponse();
    });
    expect(result.current.mode).toBe("idle");
    expect(result.current.history).toHaveLength(1);
    expect(result.current.history[0]?.role).toBe("tutor");
    expect(result.current.streamingWords).toHaveLength(0);
  });

  it("bargeIn clears streaming words and returns to idle", () => {
    const { result } = renderHook(() => useSessionStore());
    hookAct(() => {
      result.current.startTutorResponse();
      result.current.appendStreamWord("Hello");
      result.current.bargeIn();
    });
    expect(result.current.mode).toBe("idle");
    expect(result.current.streamingWords).toHaveLength(0);
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// T4-11: updateLastStudentUtterance replaces placeholder text
// ═══════════════════════════════════════════════════════════════════════════════
describe("T4-11: updateLastStudentUtterance replaces placeholder text", () => {
  it("replaces the most recent student entry text", () => {
    const { result } = renderHook(() => useSessionStore());
    hookAct(() => {
      result.current.addStudentUtterance("…");
    });
    expect(result.current.history).toHaveLength(1);
    expect(result.current.history[0]?.text).toBe("…");

    hookAct(() => {
      result.current.updateLastStudentUtterance("What is photosynthesis?");
    });
    expect(result.current.history).toHaveLength(1);
    expect(result.current.history[0]?.text).toBe("What is photosynthesis?");
    expect(result.current.history[0]?.role).toBe("student");
  });

  it("only updates the last student entry when multiple entries exist", () => {
    const { result } = renderHook(() => useSessionStore());
    // Split into separate acts so React state settles between operations
    // (commitTutorResponse sets history from a setStreamingWords updater)
    hookAct(() => {
      result.current.addStudentUtterance("First question");
    });
    hookAct(() => {
      result.current.startTutorResponse();
      result.current.appendStreamWord("Answer");
    });
    hookAct(() => {
      result.current.commitTutorResponse();
    });
    hookAct(() => {
      result.current.addStudentUtterance("…");
    });
    // History: [student: "First question", tutor: "Answer", student: "…"]
    expect(result.current.history).toHaveLength(3);

    hookAct(() => {
      result.current.updateLastStudentUtterance("Second question");
    });
    expect(result.current.history[0]?.text).toBe("First question");
    expect(result.current.history[2]?.text).toBe("Second question");
  });

  it("does nothing when history has no student entries", () => {
    const { result } = renderHook(() => useSessionStore());
    hookAct(() => {
      result.current.updateLastStudentUtterance("Should not crash");
    });
    expect(result.current.history).toHaveLength(0);
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// T4-12: LatencyPanel
// ═══════════════════════════════════════════════════════════════════════════════
describe("T4-12: LatencyPanel", () => {
  it("shows dashes when stageLatency is null", () => {
    render(<LatencyPanel stageLatency={null} />);
    const dashes = screen.getAllByText("—");
    expect(dashes).toHaveLength(4);
  });

  it("shows rounded ms values when stageLatency is provided", () => {
    render(
      <LatencyPanel
        stageLatency={{ stt_ms: 142.7, llm_ms: 298.1, tts_ms: 88.4, total_ms: 540.0 }}
      />
    );
    expect(screen.getByText("143ms")).toBeInTheDocument();
    expect(screen.getByText("298ms")).toBeInTheDocument();
    expect(screen.getByText("88ms")).toBeInTheDocument();
    expect(screen.getByText("540ms")).toBeInTheDocument();
  });

  it("assigns green dot when all values are under green budget", () => {
    // Budgets: STT<300, LLM<200, TTS<150, Total<500
    const { container } = render(
      <LatencyPanel
        stageLatency={{ stt_ms: 100, llm_ms: 150, tts_ms: 80, total_ms: 400 }}
      />
    );
    const greenDots = container.querySelectorAll(".latency-panel__dot--green");
    expect(greenDots.length).toBe(4);
  });

  it("assigns red dot when values exceed yellow budget", () => {
    // Budgets: STT>1000, LLM>400, TTS>300, Total>1000
    const { container } = render(
      <LatencyPanel
        stageLatency={{ stt_ms: 1200, llm_ms: 500, tts_ms: 400, total_ms: 1500 }}
      />
    );
    const redDots = container.querySelectorAll(".latency-panel__dot--red");
    expect(redDots.length).toBe(4);
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// T4-13: LatencyTrend
// ═══════════════════════════════════════════════════════════════════════════════
describe("T4-13: LatencyTrend", () => {
  it("shows empty state when history is empty", () => {
    render(<LatencyTrend history={[]} />);
    expect(screen.getByText(/No turns recorded/i)).toBeInTheDocument();
  });

  it("renders a row per turn with correct ms values", () => {
    render(
      <LatencyTrend
        history={[
          { turn: 1, stt_ms: 142, llm_ms: 298, tts_ms: 88, total_ms: 540 },
          { turn: 2, stt_ms: 155, llm_ms: 312, tts_ms: 91, total_ms: 570 },
        ]}
      />
    );
    expect(screen.getByText("142ms")).toBeInTheDocument();
    expect(screen.getByText("298ms")).toBeInTheDocument();
    expect(screen.getByText("570ms")).toBeInTheDocument();
  });

  it("shows up-arrow when total_ms increases", () => {
    render(
      <LatencyTrend
        history={[
          { turn: 1, stt_ms: 100, llm_ms: 200, tts_ms: 80, total_ms: 400 },
          { turn: 2, stt_ms: 120, llm_ms: 220, tts_ms: 90, total_ms: 500 },
        ]}
      />
    );
    expect(screen.getByText("↑")).toBeInTheDocument();
  });

  it("shows down-arrow when total_ms decreases", () => {
    render(
      <LatencyTrend
        history={[
          { turn: 1, stt_ms: 100, llm_ms: 200, tts_ms: 80, total_ms: 500 },
          { turn: 2, stt_ms: 90, llm_ms: 180, tts_ms: 70, total_ms: 400 },
        ]}
      />
    );
    expect(screen.getByText("↓")).toBeInTheDocument();
  });

  it("marks cell red when regression exceeds 20%", () => {
    const { container } = render(
      <LatencyTrend
        history={[
          { turn: 1, stt_ms: 100, llm_ms: 200, tts_ms: 80, total_ms: 400 },
          { turn: 2, stt_ms: 130, llm_ms: 200, tts_ms: 80, total_ms: 420 }, // stt > 120 -> red
        ]}
      />
    );
    const redCells = container.querySelectorAll(".latency-trend__cell--red");
    expect(redCells.length).toBeGreaterThan(0);
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// T4-10: BottomBar latency indicator
// ═══════════════════════════════════════════════════════════════════════════════
describe("T4-10: BottomBar latency indicator", () => {
  const noop = () => {};

  it("does not show latency when null", () => {
    render(
      <BottomBar
        mode="idle"
        latencyMs={null}
        onMicPress={noop}
        onMicRelease={noop}
        onBargeIn={noop}
      />
    );
    expect(screen.queryByText(/ms/)).not.toBeInTheDocument();
  });

  it("shows latency value when provided", () => {
    render(
      <BottomBar
        mode="idle"
        latencyMs={320}
        onMicPress={noop}
        onMicRelease={noop}
        onBargeIn={noop}
      />
    );
    expect(screen.getByText("~320ms")).toBeInTheDocument();
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// T4-16: useSessionStore — view, topic, greeting, reset
// ═══════════════════════════════════════════════════════════════════════════════
describe("T4-16: useSessionStore view/topic/greeting/reset", () => {
  it("starts with view=topic-select and topicId=null", () => {
    const { result } = renderHook(() => useSessionStore());
    expect(result.current.view).toBe("topic-select");
    expect(result.current.topicId).toBeNull();
  });

  it("setView changes the current view", () => {
    const { result } = renderHook(() => useSessionStore());
    hookAct(() => {
      result.current.setView("getting-ready");
    });
    expect(result.current.view).toBe("getting-ready");

    hookAct(() => {
      result.current.setView("lesson");
    });
    expect(result.current.view).toBe("lesson");
  });

  it("setView clears any existing error", () => {
    const { result } = renderHook(() => useSessionStore());
    hookAct(() => {
      result.current.setError("Something broke");
    });
    expect(result.current.error).toBe("Something broke");

    hookAct(() => {
      result.current.setView("getting-ready");
    });
    expect(result.current.error).toBeNull();
  });

  it("setTopic sets topicId and display name", () => {
    const { result } = renderHook(() => useSessionStore());
    hookAct(() => {
      result.current.setTopic("newtons_laws", "Newton's Laws");
    });
    expect(result.current.topicId).toBe("newtons_laws");
    expect(result.current.topic).toBe("Newton's Laws");
  });

  it("startGreeting sets mode to tutor-greeting and clears streaming words", () => {
    const { result } = renderHook(() => useSessionStore());
    // Pre-load some streaming words to verify they get cleared
    hookAct(() => {
      result.current.startTutorResponse();
      result.current.appendStreamWord("leftover");
    });
    expect(result.current.streamingWords).toHaveLength(1);

    hookAct(() => {
      result.current.startGreeting();
    });
    expect(result.current.mode).toBe("tutor-greeting");
    expect(result.current.streamingWords).toHaveLength(0);
  });

  it("reset clears all session state back to defaults", () => {
    const { result } = renderHook(() => useSessionStore());
    // Accumulate some state
    hookAct(() => {
      result.current.setMode("student-speaking");
      result.current.addStudentUtterance("Hello");
      result.current.setLatency(400);
      result.current.setStageLatency({ stt_ms: 100, llm_ms: 200, tts_ms: 80, total_ms: 400 });
      result.current.pushLatencyHistory({ turn: 1, stt_ms: 100, llm_ms: 200, tts_ms: 80, total_ms: 400 });
      result.current.setError("test error");
      result.current.setTurnInfo(3, 15);
      result.current.setSessionComplete(true);
    });
    // Verify state was accumulated
    expect(result.current.mode).toBe("student-speaking");
    expect(result.current.history).toHaveLength(1);
    expect(result.current.error).toBe("test error");
    expect(result.current.sessionComplete).toBe(true);
    expect(result.current.turnNumber).toBe(3);

    hookAct(() => {
      result.current.reset();
    });
    expect(result.current.mode).toBe("idle");
    expect(result.current.history).toHaveLength(0);
    expect(result.current.streamingWords).toHaveLength(0);
    expect(result.current.turnNumber).toBe(0);
    expect(result.current.totalTurns).toBe(15);
    expect(result.current.sessionComplete).toBe(false);
    expect(result.current.latencyMs).toBeNull();
    expect(result.current.stageLatency).toBeNull();
    expect(result.current.latencyHistory).toHaveLength(0);
    expect(result.current.error).toBeNull();
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// T4-17: BottomBar in tutor-greeting mode
// ═══════════════════════════════════════════════════════════════════════════════
describe("T4-17: BottomBar tutor-greeting mode", () => {
  const noop = () => {};

  it("mic button is disabled during tutor-greeting", () => {
    render(
      <BottomBar mode="tutor-greeting" latencyMs={null} onMicPress={noop} onMicRelease={noop} onBargeIn={noop} />
    );
    const micBtn = screen.getByRole("button", { name: /hold to speak/i });
    expect(micBtn).toBeDisabled();
  });

  it("shows greeting hint text during tutor-greeting", () => {
    render(
      <BottomBar mode="tutor-greeting" latencyMs={null} onMicPress={noop} onMicRelease={noop} onBargeIn={noop} />
    );
    expect(screen.getByText("Socrates VI is introducing the topic…")).toBeInTheDocument();
  });

  it("interrupt button is disabled during tutor-greeting", () => {
    render(
      <BottomBar mode="tutor-greeting" latencyMs={null} onMicPress={noop} onMicRelease={noop} onBargeIn={noop} />
    );
    const bargeBtn = screen.getByRole("button", { name: /interrupt/i });
    expect(bargeBtn).toBeDisabled();
  });
});

// ═══════════════════════════════════════════════════════════════════════════════
// T4-18: CelebrationOverlay
// ═══════════════════════════════════════════════════════════════════════════════
describe("T4-18: CelebrationOverlay", () => {
  const defaultProps = {
    topic: "Photosynthesis",
    turnCount: 15,
    totalTurns: 15,
    onTryAnother: vi.fn(),
  };

  it("renders the celebration title", () => {
    render(<CelebrationOverlay {...defaultProps} />);
    expect(screen.getByText("Amazing work!")).toBeInTheDocument();
  });

  it("displays the topic name", () => {
    render(<CelebrationOverlay {...defaultProps} />);
    expect(screen.getByText("Photosynthesis")).toBeInTheDocument();
  });

  it("shows turn count and total stats", () => {
    render(<CelebrationOverlay {...defaultProps} />);
    const fifteens = screen.getAllByText("15");
    expect(fifteens).toHaveLength(2); // turnCount + totalTurns
    expect(screen.getByText("Questions")).toBeInTheDocument();
    expect(screen.getByText("Total turns")).toBeInTheDocument();
  });

  it("renders 'Try another topic' button", () => {
    render(<CelebrationOverlay {...defaultProps} />);
    const btn = screen.getByRole("button", { name: /try another topic/i });
    expect(btn).toBeInTheDocument();
  });

  it("fires onTryAnother callback when CTA is clicked", () => {
    const onTryAnother = vi.fn();
    render(<CelebrationOverlay {...defaultProps} onTryAnother={onTryAnother} />);
    fireEvent.click(screen.getByRole("button", { name: /try another topic/i }));
    expect(onTryAnother).toHaveBeenCalledOnce();
  });

  it("has dialog role for accessibility", () => {
    render(<CelebrationOverlay {...defaultProps} />);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("renders confetti particles", () => {
    const { container } = render(<CelebrationOverlay {...defaultProps} />);
    const particles = container.querySelectorAll(".celebration__particle");
    expect(particles.length).toBe(40);
  });
});
