import { useState, useCallback } from "react";
import type { AppView, SessionMode, TopicId, ConversationEntry, SessionStore, StageLatency, TurnLatency, LessonVisualState } from "./types";

/** Null-safe merge helper: merges `patch` into an existing StageLatency, or drops it if null. */
function mergeStage(prev: StageLatency | null, patch: Partial<StageLatency>): StageLatency | null {
  if (prev === null) return null;
  return { ...prev, ...patch };
}

function makeId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
}

export function useSessionStore(): SessionStore {
  const [view, setViewState] = useState<AppView>("topic-select");
  const [mode, setModeState] = useState<SessionMode>("idle");
  const [topic, setTopicDisplay] = useState("Photosynthesis");
  const [topicId, setTopicIdState] = useState<TopicId | null>(null);
  const [latencyMs, setLatencyMs] = useState<number | null>(null);
  const [stageLatency, setStageLatencyState] = useState<StageLatency | null>(null);
  const [latencyHistory, setLatencyHistory] = useState<TurnLatency[]>([]);
  const [history, setHistory] = useState<ConversationEntry[]>([]);
  const [streamingWords, setStreamingWords] = useState<string[]>([]);
  // Turn number is now driven by the backend (via timing.turn_number).
  // Start at 0 — will be set to 1 after the first turn completes.
  const [turnNumber, setTurnNumber] = useState(0);
  const [totalTurns, setTotalTurns] = useState(15);
  const [sessionComplete, setSessionCompleteState] = useState(false);
  const [error, setErrorState] = useState<string | null>(null);
  const [visual, setVisualState] = useState<LessonVisualState | null>(null);

  const setView = useCallback((v: AppView) => {
    setViewState(v);
    setErrorState(null);
  }, []);

  const setTopic = useCallback((id: TopicId, displayName: string) => {
    setTopicIdState(id);
    setTopicDisplay(displayName);
  }, []);

  const setMode = useCallback((m: SessionMode) => setModeState(m), []);
  const setLatency = useCallback((ms: number) => setLatencyMs(ms), []);
  const setStageLatency = useCallback((latency: StageLatency) => setStageLatencyState(latency), []);
  const pushLatencyHistory = useCallback((entry: TurnLatency) => {
    setLatencyHistory((prev) => [...prev.slice(-4), entry]); // keep last 5
  }, []);

  const setResponseComplete = useCallback((ms: number) => {
    setStageLatencyState((prev) => mergeStage(prev, { response_complete_ms: ms }));
  }, []);

  const setLipSync = useCallback((ms: number) => {
    setStageLatencyState((prev) => mergeStage(prev, { lip_sync_ms: ms }));
  }, []);

  const updateLastLatencyHistory = useCallback((update: Partial<Omit<TurnLatency, "turn">>) => {
    setLatencyHistory((prev) => {
      if (prev.length === 0) return prev;
      const last = prev[prev.length - 1]!;
      return [...prev.slice(0, -1), { ...last, ...update }];
    });
  }, []);
  const setError = useCallback((msg: string | null) => setErrorState(msg), []);
  const setVisual = useCallback((v: LessonVisualState | null) => setVisualState(v), []);

  const setTurnInfo = useCallback((tn: number, tt: number) => {
    setTurnNumber(tn);
    setTotalTurns(tt);
  }, []);

  const setSessionComplete = useCallback((complete: boolean) => {
    setSessionCompleteState(complete);
  }, []);

  const addStudentUtterance = useCallback((text: string) => {
    setHistory((prev) => [
      ...prev,
      { id: makeId(), role: "student", text, timestamp: Date.now() },
    ]);
  }, []);

  const startGreeting = useCallback(() => {
    setStreamingWords([]);
    setModeState("tutor-greeting");
  }, []);

  const startTutorResponse = useCallback(() => {
    setStreamingWords([]);
    setModeState("tutor-responding");
  }, []);

  const appendStreamWord = useCallback((word: string) => {
    setStreamingWords((prev) => [...prev, word]);
  }, []);

  const commitTutorResponse = useCallback(() => {
    setStreamingWords((prev) => {
      const fullText = prev.join(" ");
      if (fullText.trim()) {
        setHistory((h) => [
          ...h,
          { id: makeId(), role: "tutor", text: fullText, timestamp: Date.now() },
        ]);
        // Turn number is set by setTurnInfo from the backend —
        // no frontend increment needed.
      }
      return [];
    });
    setModeState("idle");
  }, []);

  const updateLastStudentUtterance = useCallback((text: string) => {
    setHistory((prev) => {
      for (let i = prev.length - 1; i >= 0; i--) {
        if (prev[i].role === "student") {
          const updated = [...prev];
          updated[i] = { ...updated[i], text };
          return updated;
        }
      }
      return prev;
    });
  }, []);

  const removeLastStudentUtterance = useCallback(() => {
    setHistory((prev) => {
      for (let i = prev.length - 1; i >= 0; i--) {
        if (prev[i].role === "student") {
          return [...prev.slice(0, i), ...prev.slice(i + 1)];
        }
      }
      return prev;
    });
  }, []);

  const bargeIn = useCallback(() => {
    setStreamingWords((prev) => {
      const partial = prev.join(" ");
      if (partial.trim()) {
        setHistory((h) => [
          ...h,
          {
            id: makeId(),
            role: "tutor",
            text: `${partial}…`,
            timestamp: Date.now(),
          },
        ]);
      }
      return [];
    });
    setModeState("idle");
  }, []);

  const restoreSession = useCallback(
    (restoredHistory: ConversationEntry[], restoredTurnNumber: number, restoredTotalTurns: number) => {
      setHistory(restoredHistory);
      setTurnNumber(restoredTurnNumber);
      setTotalTurns(restoredTotalTurns);
      setStreamingWords([]);
      setModeState("idle");
      setSessionCompleteState(false);
      setErrorState(null);
      setVisualState(null);
    },
    [],
  );

  const reset = useCallback(() => {
    setModeState("idle");
    setHistory([]);
    setStreamingWords([]);
    setTurnNumber(0);
    setTotalTurns(15);
    setSessionCompleteState(false);
    setLatencyMs(null);
    setStageLatencyState(null);
    setLatencyHistory([]);
    setErrorState(null);
    setVisualState(null);
  }, []);

  return {
    view,
    mode,
    topic,
    topicId,
    grade: 8,
    turnNumber,
    totalTurns,
    sessionComplete,
    latencyMs,
    stageLatency,
    latencyHistory,
    history,
    streamingWords,
    error,
    visual,
    setVisual,
    setView,
    setTopic,
    setMode,
    setLatency,
    setStageLatency,
    pushLatencyHistory,
    setResponseComplete,
    setLipSync,
    updateLastLatencyHistory,
    setError,
    setTurnInfo,
    setSessionComplete,
    addStudentUtterance,
    updateLastStudentUtterance,
    removeLastStudentUtterance,
    startGreeting,
    startTutorResponse,
    appendStreamWord,
    commitTutorResponse,
    bargeIn,
    restoreSession,
    reset,
  };
}
