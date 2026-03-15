/**
 * Tests for useTutorSocket hook.
 *
 * Verifies:
 * - WebSocket connects once on mount and stays stable across re-renders
 *   (THE critical regression test for the reconnect-on-every-render bug)
 * - Binary audio chunks are sent when WS is open
 * - WS-not-open sends surface connection errors and retry behavior
 * - JSON control messages (end_of_utterance, barge_in) are sent correctly
 * - Server messages are dispatched to the correct store methods
 * - Callback stability: sendAudioChunk/sendEndOfUtterance don't change
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useTutorSocket } from "./useTutorSocket";
import type { SessionStore } from "./types";

// ── Mock WebSocket ─────────────────────────────────────────────────────────

class MockWebSocket {
  static instances: MockWebSocket[] = [];
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  url: string;
  binaryType = "blob";
  readyState = MockWebSocket.CONNECTING;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  send = vi.fn();
  close = vi.fn(() => {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.();
  });

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
    // Auto-open after microtask (simulates async connection)
    queueMicrotask(() => {
      if (this.readyState === MockWebSocket.CONNECTING) {
        this.readyState = MockWebSocket.OPEN;
        this.onopen?.();
      }
    });
  }

  /** Helper to simulate server sending a JSON message */
  _receiveMessage(data: object): void {
    this.onmessage?.({ data: JSON.stringify(data) });
  }
}

function makeStore(overrides?: Partial<SessionStore>): SessionStore {
  return {
    view: "lesson" as const,
    topicId: "photosynthesis" as const,
    mode: "idle",
    topic: "Test",
    grade: 8,
    turnNumber: 1,
    totalTurns: 15,
    sessionComplete: false,
    latencyMs: null,
    stageLatency: null,
    latencyHistory: [],
    history: [],
    streamingWords: [],
    error: null,
    visual: null,
    setVisual: vi.fn(),
    setView: vi.fn(),
    setTopic: vi.fn(),
    setMode: vi.fn(),
    setLatency: vi.fn(),
    setStageLatency: vi.fn(),
    pushLatencyHistory: vi.fn(),
    setError: vi.fn(),
    setTurnInfo: vi.fn(),
    setSessionComplete: vi.fn(),
    addStudentUtterance: vi.fn(),
    updateLastStudentUtterance: vi.fn(),
    removeLastStudentUtterance: vi.fn(),
    startTutorResponse: vi.fn(),
    startGreeting: vi.fn(),
    appendStreamWord: vi.fn(),
    commitTutorResponse: vi.fn(),
    bargeIn: vi.fn(),
    restoreSession: vi.fn(),
    reset: vi.fn(),
    ...overrides,
  };
}

beforeEach(() => {
  MockWebSocket.instances = [];
  // @ts-expect-error — mock
  globalThis.WebSocket = MockWebSocket;
  // Provide static constants that code may reference via WebSocket.OPEN etc.
  (globalThis.WebSocket as unknown as Record<string, number>).OPEN = 1;
  (globalThis.WebSocket as unknown as Record<string, number>).CONNECTING = 0;
  (globalThis.WebSocket as unknown as Record<string, number>).CLOSED = 3;

  // Mock AudioContext (used for TTS playback inside the hook)
  // @ts-expect-error — mock
  globalThis.AudioContext = vi.fn(() => ({
    createBuffer: vi.fn(() => ({ getChannelData: () => new Float32Array(0) })),
    createBufferSource: vi.fn(() => ({
      connect: vi.fn(),
      start: vi.fn(),
      buffer: null,
      onended: null,
    })),
    decodeAudioData: vi.fn(),
    destination: {},
    close: vi.fn().mockResolvedValue(undefined),
    state: "running",
    sampleRate: 16000,
  }));
  localStorage.clear();
  window.history.replaceState({}, "", "/");
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ── Tests ──────────────────────────────────────────────────────────────────

describe("useTutorSocket", () => {
  describe("WebSocket lifecycle", () => {
    it("creates exactly ONE WebSocket on mount", async () => {
      const store = makeStore();
      renderHook(() => useTutorSocket({ store, serverUrl: "ws://test/session" }));
      await vi.waitFor(() => expect(MockWebSocket.instances).toHaveLength(1));
    });

    it("CRITICAL: does NOT reconnect when store object changes (re-render)", async () => {
      // This is THE regression test for the bug that caused all audio to be dropped.
      // Before the fix, every re-render created a new store object reference,
      // which caused handleMessage → connect → useEffect to disconnect + reconnect.
      const store1 = makeStore();
      const { rerender } = renderHook(
        (props) => useTutorSocket({ store: props.store, serverUrl: "ws://test/session" }),
        { initialProps: { store: store1 } }
      );

      await vi.waitFor(() => expect(MockWebSocket.instances).toHaveLength(1));
      const firstWs = MockWebSocket.instances[0];

      // Simulate re-render with a new store object (same shape, different reference)
      // This happens on EVERY React state change in the parent component
      const store2 = makeStore();
      rerender({ store: store2 });

      // Still only 1 WebSocket — no reconnection!
      expect(MockWebSocket.instances).toHaveLength(1);
      expect(firstWs.close).not.toHaveBeenCalled();
    });

    it("CRITICAL: WS stays alive through multiple rapid re-renders", async () => {
      const store = makeStore();
      const { rerender } = renderHook(
        (props) => useTutorSocket({ store: props.store, serverUrl: "ws://test/session" }),
        { initialProps: { store } }
      );

      await vi.waitFor(() => expect(MockWebSocket.instances).toHaveLength(1));

      // Simulate 10 rapid re-renders (like a mode change triggering cascading updates)
      for (let i = 0; i < 10; i++) {
        rerender({ store: makeStore() });
      }

      // MUST still be exactly 1 WebSocket
      expect(MockWebSocket.instances).toHaveLength(1);
      expect(MockWebSocket.instances[0].close).not.toHaveBeenCalled();
    });

    it("disconnects on unmount", async () => {
      const store = makeStore();
      const { unmount } = renderHook(() =>
        useTutorSocket({ store, serverUrl: "ws://test/session" })
      );

      await vi.waitFor(() => expect(MockWebSocket.instances).toHaveLength(1));
      const ws = MockWebSocket.instances[0];

      unmount();
      expect(ws.close).toHaveBeenCalled();
    });

    it("reconnects after unexpected close", async () => {
      const store = makeStore();
      renderHook(() => useTutorSocket({ store, serverUrl: "ws://test/session" }));
      await vi.waitFor(() => expect(MockWebSocket.instances[0]?.readyState).toBe(1));

      const firstWs = MockWebSocket.instances[0];
      act(() => {
        firstWs.close();
      });

      await vi.waitFor(() => expect(MockWebSocket.instances.length).toBe(2));
      expect(store.setError).toHaveBeenCalled();
    });

    it("restores only when session_id is present in the URL", async () => {
      localStorage.setItem("tutorSessionAvatar", "simli");
      window.history.replaceState({}, "", "/?session_id=url-session");

      const store = makeStore({ topicId: "photosynthesis" as const });
      renderHook(() => useTutorSocket({ store, serverUrl: "ws://test/session", topicId: "photosynthesis" }));

      await vi.waitFor(() => expect(MockWebSocket.instances).toHaveLength(1));
      expect(MockWebSocket.instances[0]?.url).toBe("ws://test/session?topic=photosynthesis&session_id=url-session&avatar=simli");
    });

    it("does not restore from localStorage when the URL has no session_id", async () => {
      localStorage.setItem("tutorSessionId", "saved-session");
      localStorage.setItem("tutorSessionTopicId", "photosynthesis");
      localStorage.setItem("tutorSessionAvatar", "simli");

      const store = makeStore({ topicId: "photosynthesis" as const });
      renderHook(() => useTutorSocket({ store, serverUrl: "ws://test/session", topicId: "photosynthesis" }));

      await vi.waitFor(() => expect(MockWebSocket.instances).toHaveLength(1));
      expect(MockWebSocket.instances[0]?.url).toBe("ws://test/session?topic=photosynthesis&avatar=simli");
    });

    it("does not restore when the avatar provider changes", async () => {
      localStorage.setItem("tutorSessionAvatar", "simli");
      window.history.replaceState({}, "", "/?session_id=saved-session&avatar=spatialreal");

      const store = makeStore({ topicId: "photosynthesis" as const });
      renderHook(() => useTutorSocket({ store, serverUrl: "ws://test/session", topicId: "photosynthesis" }));

      await vi.waitFor(() => expect(MockWebSocket.instances).toHaveLength(1));
      expect(MockWebSocket.instances[0]?.url).toBe("ws://test/session?topic=photosynthesis&avatar=spatialreal");
    });
  });

  describe("Sending messages", () => {
    it("sendAudioChunk sends binary data when WS is open", async () => {
      const store = makeStore();
      const { result } = renderHook(() =>
        useTutorSocket({ store, serverUrl: "ws://test/session" })
      );

      await vi.waitFor(() => expect(MockWebSocket.instances[0]?.readyState).toBe(1));

      const chunk = new ArrayBuffer(1024);
      result.current.sendAudioChunk(chunk);

      expect(MockWebSocket.instances[0].send).toHaveBeenCalledWith(chunk);
    });

    it("sendAudioChunk reports connection issue when WS is not open", () => {
      const store = makeStore();
      const { result } = renderHook(() =>
        useTutorSocket({ store, serverUrl: "ws://test/session" })
      );

      // WS is still CONNECTING (hasn't opened yet)
      const chunk = new ArrayBuffer(1024);
      result.current.sendAudioChunk(chunk);

      expect(MockWebSocket.instances[0].send).not.toHaveBeenCalled();
      expect(store.setError).toHaveBeenCalled();
    });

    it("sendEndOfUtterance sends correct JSON message", async () => {
      const store = makeStore();
      const { result } = renderHook(() =>
        useTutorSocket({ store, serverUrl: "ws://test/session" })
      );

      await vi.waitFor(() => expect(MockWebSocket.instances[0]?.readyState).toBe(1));

      result.current.sendEndOfUtterance();

      expect(MockWebSocket.instances[0].send).toHaveBeenCalledWith(
        JSON.stringify({ type: "end_of_utterance" })
      );
    });

    it("sendBargeIn sends correct JSON message", async () => {
      const store = makeStore();
      const { result } = renderHook(() =>
        useTutorSocket({ store, serverUrl: "ws://test/session" })
      );

      await vi.waitFor(() => expect(MockWebSocket.instances[0]?.readyState).toBe(1));

      result.current.sendBargeIn();

      expect(MockWebSocket.instances[0].send).toHaveBeenCalledWith(
        JSON.stringify({ type: "barge_in" })
      );
    });

    it("sendEndOfUtterance reports connection issue when WS is not open", () => {
      const store = makeStore();
      const { result } = renderHook(() =>
        useTutorSocket({ store, serverUrl: "ws://test/session" })
      );

      result.current.sendEndOfUtterance();

      expect(MockWebSocket.instances[0].send).not.toHaveBeenCalled();
      expect(store.setError).toHaveBeenCalled();
    });
  });

  describe("Receiving server messages", () => {
    it("session_start calls store.setMode('idle') and onSessionStart", async () => {
      const store = makeStore();
      const onSessionStart = vi.fn();
      const { result } = renderHook(() =>
        useTutorSocket({ store, serverUrl: "ws://test/session", onSessionStart })
      );

      await vi.waitFor(() => expect(MockWebSocket.instances[0]?.readyState).toBe(1));
      const ws = MockWebSocket.instances[0];

      act(() => {
        ws._receiveMessage({ type: "session_start", session_id: "abc-123" });
      });

      expect(store.setMode).toHaveBeenCalledWith("idle");
      expect(onSessionStart).toHaveBeenCalledWith("start");
      expect(result.current.sessionKind).toBe("start");
      expect(new URLSearchParams(window.location.search).get("session_id")).toBe("abc-123");
    });

    it("session_restore restores history and marks the session as resumable", async () => {
      localStorage.setItem("tutorSessionAvatar", "simli");
      const store = makeStore();
      const onSessionStart = vi.fn();
      const { result } = renderHook(() =>
        useTutorSocket({ store, serverUrl: "ws://test/session", onSessionStart })
      );

      await vi.waitFor(() => expect(MockWebSocket.instances[0]?.readyState).toBe(1));
      const ws = MockWebSocket.instances[0];

      act(() => {
        ws._receiveMessage({
          type: "session_restore",
          session_id: "resume-123",
          topic: "photosynthesis",
          turn_count: 4,
          total_turns: 15,
          avatar_provider: "simli",
          history: [{ role: "assistant", content: "What do you think plants need?" }],
        });
      });

      expect(store.restoreSession).toHaveBeenCalled();
      expect(onSessionStart).toHaveBeenCalledWith("restore");
      expect(result.current.sessionKind).toBe("restore");
      expect(new URLSearchParams(window.location.search).get("session_id")).toBe("resume-123");
    });

    it("reconnect with freshSession clears persisted session before reconnecting", async () => {
      localStorage.setItem("tutorSessionAvatar", "simli");
      window.history.replaceState({}, "", "/?session_id=saved-session");

      const store = makeStore({ topicId: "photosynthesis" as const });
      const { result } = renderHook(() =>
        useTutorSocket({ store, serverUrl: "ws://test/session", topicId: "photosynthesis" })
      );

      await vi.waitFor(() => expect(MockWebSocket.instances[0]?.readyState).toBe(1));

      act(() => {
        result.current.reconnect({ freshSession: true });
      });

      await vi.waitFor(() => expect(MockWebSocket.instances).toHaveLength(2));
      expect(localStorage.getItem("tutorSessionId")).toBeNull();
      expect(localStorage.getItem("tutorSessionTopicId")).toBeNull();
      expect(localStorage.getItem("tutorSessionAvatar")).toBeNull();
      expect(new URLSearchParams(window.location.search).get("session_id")).toBeNull();
      expect(MockWebSocket.instances[1]?.url).toBe("ws://test/session?topic=photosynthesis&avatar=simli");
    });

    it("error message calls store.setMode('idle') and logs", async () => {
      const store = makeStore();
      renderHook(() => useTutorSocket({ store, serverUrl: "ws://test/session" }));

      await vi.waitFor(() => expect(MockWebSocket.instances[0]?.readyState).toBe(1));
      const ws = MockWebSocket.instances[0];

      act(() => {
        ws._receiveMessage({ type: "error", code: "TEST_ERROR", message: "test" });
      });

      expect(store.setMode).toHaveBeenCalledWith("idle");
    });

    it("audio_chunk forwards decoded PCM bytes to onAudioChunk callback", async () => {
      const store = makeStore();
      const onAudioChunk = vi.fn();
      renderHook(() =>
        useTutorSocket({ store, serverUrl: "ws://test/session", onAudioChunk })
      );
      await vi.waitFor(() => expect(MockWebSocket.instances[0]?.readyState).toBe(1));
      const ws = MockWebSocket.instances[0];

      act(() => {
        ws._receiveMessage({ type: "audio_chunk", data: "AAECAw==" });
      });

      expect(onAudioChunk).toHaveBeenCalledTimes(1);
      const arg = onAudioChunk.mock.calls[0][0] as Uint8Array;
      expect(Array.from(arg)).toEqual([0, 1, 2, 3]);
    });

    it("audio_chunk can suppress browser playback while still forwarding decoded PCM", async () => {
      const store = makeStore();
      const onAudioChunk = vi.fn();
      renderHook(() =>
        useTutorSocket({
          store,
          serverUrl: "ws://test/session",
          onAudioChunk,
          shouldPlayAudioChunk: () => false,
        })
      );
      await vi.waitFor(() => expect(MockWebSocket.instances[0]?.readyState).toBe(1));
      const ws = MockWebSocket.instances[0];

      act(() => {
        ws._receiveMessage({ type: "audio_chunk", data: "AAECAw==" });
      });

      expect(onAudioChunk).toHaveBeenCalledTimes(1);
      expect(globalThis.AudioContext).not.toHaveBeenCalled();
    });

    it("student_partial calls store.updateLastStudentUtterance", async () => {
      const store = makeStore();
      renderHook(() => useTutorSocket({ store, serverUrl: "ws://test/session" }));

      await vi.waitFor(() => expect(MockWebSocket.instances[0]?.readyState).toBe(1));
      const ws = MockWebSocket.instances[0];

      act(() => {
        ws._receiveMessage({ type: "student_partial", text: "What is photo" });
      });

      expect(store.updateLastStudentUtterance).toHaveBeenCalledWith("What is photo");
    });

    it("student_partial updates progressively as more text arrives", async () => {
      const store = makeStore();
      renderHook(() => useTutorSocket({ store, serverUrl: "ws://test/session" }));

      await vi.waitFor(() => expect(MockWebSocket.instances[0]?.readyState).toBe(1));
      const ws = MockWebSocket.instances[0];

      act(() => {
        ws._receiveMessage({ type: "student_partial", text: "What" });
      });
      act(() => {
        ws._receiveMessage({ type: "student_partial", text: "What is photo" });
      });
      act(() => {
        ws._receiveMessage({ type: "student_partial", text: "What is photosynthesis" });
      });

      expect(store.updateLastStudentUtterance).toHaveBeenCalledTimes(3);
      expect(store.updateLastStudentUtterance).toHaveBeenLastCalledWith("What is photosynthesis");
    });

    it("barge_in_ack calls store.bargeIn()", async () => {
      const store = makeStore();
      renderHook(() => useTutorSocket({ store, serverUrl: "ws://test/session" }));

      await vi.waitFor(() => expect(MockWebSocket.instances[0]?.readyState).toBe(1));
      const ws = MockWebSocket.instances[0];

      act(() => {
        ws._receiveMessage({ type: "barge_in_ack" });
      });

      expect(store.bargeIn).toHaveBeenCalled();
    });

    it("stages visual updates until the matching tutor response is committed", async () => {
      vi.useFakeTimers();
      try {
        const store = makeStore({ turnNumber: 0, totalTurns: 15 });
        renderHook(() => useTutorSocket({ store, serverUrl: "ws://test/session" }));
        await vi.waitFor(() => expect(MockWebSocket.instances[0]?.readyState).toBe(1));
        const ws = MockWebSocket.instances[0];

        act(() => {
          ws._receiveMessage({
            type: "tutor_text_chunk",
            text: "Think about the air.",
            timing: {
              turn_number: 1,
              total_turns: 15,
              stt_finish_ms: 100,
              llm_duration_ms: 200,
              tts_duration_ms: 150,
              turn_duration_ms: 450,
            },
          });
          ws._receiveMessage({
            type: "lesson_visual_update",
            diagram_id: "photosynthesis",
            step_id: 0,
            step_label: "The Hook",
            total_steps: 7,
            highlight_keys: ["sunlight"],
            unlocked_elements: ["sunlight", "water", "roots"],
            progress_completed: 3,
            progress_total: 10,
            progress_label: "Scene Pieces Unlocked: 3/10",
            caption: "The picture is filling in.",
            emoji_diagram: "☀️ + 💧 + CO2",
            turn_number: 1,
            is_recap: false,
          });
        });

        expect(store.setVisual).not.toHaveBeenCalled();
        expect(store.setTurnInfo).not.toHaveBeenCalledWith(1, 15);
        expect(store.commitTutorResponse).not.toHaveBeenCalled();

        act(() => {
          vi.advanceTimersByTime(400);
        });

        expect(store.setTurnInfo).toHaveBeenCalledWith(1, 15);
        expect(store.commitTutorResponse).toHaveBeenCalledTimes(1);
        expect(store.setVisual).toHaveBeenCalledWith({
          diagramId: "photosynthesis",
          stepId: 0,
          stepLabel: "The Hook",
          totalSteps: 7,
          highlightKeys: ["sunlight"],
          unlockedElements: ["sunlight", "water", "roots"],
          progressCompleted: 3,
          progressTotal: 10,
          progressLabel: "Scene Pieces Unlocked: 3/10",
          caption: "The picture is filling in.",
          emojiDiagram: "☀️ + 💧 + CO2",
          turnNumber: 1,
          isRecap: false,
        });
      } finally {
        vi.useRealTimers();
      }
    });

    it("stages session completion until the tutor response commit finishes", async () => {
      vi.useFakeTimers();
      try {
        const store = makeStore({ turnNumber: 0, totalTurns: 15 });
        renderHook(() => useTutorSocket({ store, serverUrl: "ws://test/session" }));
        await vi.waitFor(() => expect(MockWebSocket.instances[0]?.readyState).toBe(1));
        const ws = MockWebSocket.instances[0];

        act(() => {
          ws._receiveMessage({
            type: "tutor_text_chunk",
            text: "Great work.",
            timing: {
              turn_number: 1,
              total_turns: 1,
              stt_finish_ms: 80,
              llm_duration_ms: 120,
              tts_duration_ms: 90,
              turn_duration_ms: 320,
            },
          });
          ws._receiveMessage({
            type: "session_complete",
            turn_number: 1,
            total_turns: 1,
            message: "Great job!",
          });
        });

        expect(store.setSessionComplete).not.toHaveBeenCalled();

        act(() => {
          vi.advanceTimersByTime(400);
        });

        expect(store.commitTutorResponse).toHaveBeenCalledTimes(1);
        expect(store.setSessionComplete).toHaveBeenCalledWith(true);
        expect(store.setTurnInfo).toHaveBeenCalledWith(1, 1);
      } finally {
        vi.useRealTimers();
      }
    });

    it("ignores stale visual updates from older turns", async () => {
      const store = makeStore();
      renderHook(() => useTutorSocket({ store, serverUrl: "ws://test/session" }));
      await vi.waitFor(() => expect(MockWebSocket.instances[0]?.readyState).toBe(1));
      const ws = MockWebSocket.instances[0];

      act(() => {
        ws._receiveMessage({
          type: "session_restore",
          session_id: "resume-123",
          topic: "photosynthesis",
          turn_count: 2,
          total_turns: 15,
          avatar_provider: "simli",
          history: [],
        });
        ws._receiveMessage({
          type: "lesson_visual_update",
          diagram_id: "photosynthesis",
          step_id: 2,
          step_label: "The Green Kitchen",
          total_steps: 7,
          highlight_keys: ["chloroplast"],
          caption: "Leaf kitchen",
          emoji_diagram: "🌿 -> 🏭",
          turn_number: 2,
          is_recap: false,
        });
        ws._receiveMessage({
          type: "lesson_visual_update",
          diagram_id: "photosynthesis",
          step_id: 0,
          step_label: "The Hook",
          total_steps: 7,
          highlight_keys: ["seed"],
          caption: "Old state",
          emoji_diagram: "🌱 -> ?",
          turn_number: 1,
          is_recap: false,
        });
      });

      expect(store.setVisual).toHaveBeenCalledTimes(1);
      expect(store.setVisual).toHaveBeenLastCalledWith(
        expect.objectContaining({ stepId: 2, turnNumber: 2 }),
      );
    });

    it("tutor_text_chunk with timing calls setStageLatency and pushLatencyHistory", async () => {
      const store = makeStore();
      renderHook(() => useTutorSocket({ store, serverUrl: "ws://test/session" }));
      await vi.waitFor(() => expect(MockWebSocket.instances[0]?.readyState).toBe(1));
      const ws = MockWebSocket.instances[0];

      act(() => {
        ws._receiveMessage({
          type: "tutor_text_chunk",
          text: "Great question!",
          timing: {
            stt_finish_ms: 120,
            llm_duration_ms: 180,
            tts_duration_ms: 95,
            turn_duration_ms: 650,
          },
        });
      });

      expect(store.setStageLatency).toHaveBeenCalledWith({
        stt_ms: 120,
        llm_ms: 180,
        tts_ms: 95,
        total_ms: 650,
      });
      expect(store.pushLatencyHistory).toHaveBeenCalledWith(
        expect.objectContaining({ stt_ms: 120, llm_ms: 180, tts_ms: 95, total_ms: 650 })
      );
    });

    it("tutor_text_chunk notifies when the streamed tutor audio round is complete", async () => {
      const store = makeStore();
      const onAudioStreamComplete = vi.fn();
      renderHook(() =>
        useTutorSocket({ store, serverUrl: "ws://test/session", onAudioStreamComplete })
      );
      await vi.waitFor(() => expect(MockWebSocket.instances[0]?.readyState).toBe(1));
      const ws = MockWebSocket.instances[0];

      act(() => {
        ws._receiveMessage({
          type: "tutor_text_chunk",
          text: "Great question!",
          timing: {
            stt_finish_ms: 120,
            llm_duration_ms: 180,
            tts_duration_ms: 95,
            turn_duration_ms: 650,
          },
        });
      });

      expect(onAudioStreamComplete).toHaveBeenCalledTimes(1);
    });

    it("tutor_text_chunk with null timing values still calls setStageLatency", async () => {
      const store = makeStore();
      renderHook(() => useTutorSocket({ store, serverUrl: "ws://test/session" }));
      await vi.waitFor(() => expect(MockWebSocket.instances[0]?.readyState).toBe(1));
      const ws = MockWebSocket.instances[0];

      act(() => {
        ws._receiveMessage({
          type: "tutor_text_chunk",
          text: "Great question!",
          timing: { stt_finish_ms: 120, llm_duration_ms: 180, tts_duration_ms: null, turn_duration_ms: 450 },
        });
      });

      expect(store.setStageLatency).toHaveBeenCalledWith({
        stt_ms: 120,
        llm_ms: 180,
        tts_ms: null,
        total_ms: 450,
      });
    });

    it("tutor_text_chunk without timing field does not call setStageLatency", async () => {
      const store = makeStore();
      renderHook(() => useTutorSocket({ store, serverUrl: "ws://test/session" }));
      await vi.waitFor(() => expect(MockWebSocket.instances[0]?.readyState).toBe(1));
      const ws = MockWebSocket.instances[0];

      act(() => {
        // Send tutor_text_chunk with no timing key at all
        ws.onmessage?.({ data: JSON.stringify({ type: "tutor_text_chunk", text: "Hi" }) });
      });

      expect(store.setStageLatency).not.toHaveBeenCalled();
      expect(store.pushLatencyHistory).not.toHaveBeenCalled();
    });

    it("error with partial timing calls setStageLatency and setMode('idle')", async () => {
      const store = makeStore();
      renderHook(() => useTutorSocket({ store, serverUrl: "ws://test/session" }));
      await vi.waitFor(() => expect(MockWebSocket.instances[0]?.readyState).toBe(1));
      const ws = MockWebSocket.instances[0];

      act(() => {
        ws._receiveMessage({
          type: "error",
          code: "TURN_FAILED",
          message: "[tts/cartesia] APIConnectionError: Connection error.",
          timing: {
            stt_finish_ms: 130,
            llm_duration_ms: 190,
            tts_duration_ms: null,
            turn_duration_ms: 420,
          },
        });
      });

      expect(store.setStageLatency).toHaveBeenCalledWith({
        stt_ms: 130,
        llm_ms: 190,
        tts_ms: null,
        total_ms: 420,
      });
      expect(store.pushLatencyHistory).toHaveBeenCalled();
      expect(store.setMode).toHaveBeenCalledWith("idle");
    });

    it("error without timing does not call setStageLatency", async () => {
      const store = makeStore();
      renderHook(() => useTutorSocket({ store, serverUrl: "ws://test/session" }));
      await vi.waitFor(() => expect(MockWebSocket.instances[0]?.readyState).toBe(1));
      const ws = MockWebSocket.instances[0];

      act(() => {
        ws._receiveMessage({ type: "error", code: "TEST_ERROR" });
      });

      expect(store.setStageLatency).not.toHaveBeenCalled();
      expect(store.setMode).toHaveBeenCalledWith("idle");
    });

    it("simli error routes via onSimliError and does not force idle mode", async () => {
      const store = makeStore();
      const onSimliError = vi.fn();
      renderHook(() =>
        useTutorSocket({ store, serverUrl: "ws://test/session", onSimliError })
      );
      await vi.waitFor(() => expect(MockWebSocket.instances[0]?.readyState).toBe(1));
      const ws = MockWebSocket.instances[0];

      act(() => {
        ws._receiveMessage({
          type: "error",
          code: "SIMLI_CONNECT_FAILED",
          message: "simli failed",
        });
      });

      expect(onSimliError).toHaveBeenCalledTimes(1);
      expect(store.setMode).not.toHaveBeenCalledWith("idle");
    });

    it("uses latest store callbacks even after re-render (optsRef pattern)", async () => {
      const store1 = makeStore();
      const { rerender } = renderHook(
        (props) => useTutorSocket({ store: props.store, serverUrl: "ws://test/session" }),
        { initialProps: { store: store1 } }
      );

      await vi.waitFor(() => expect(MockWebSocket.instances[0]?.readyState).toBe(1));

      // Re-render with a DIFFERENT store (new callbacks)
      const store2 = makeStore();
      rerender({ store: store2 });

      // Send a message — should call store2's methods, not store1's
      act(() => {
        MockWebSocket.instances[0]._receiveMessage({ type: "barge_in_ack" });
      });

      expect(store1.bargeIn).not.toHaveBeenCalled();
      expect(store2.bargeIn).toHaveBeenCalled();
    });
  });

  describe("Callback stability", () => {
    it("sendAudioChunk reference is stable across re-renders", async () => {
      const store = makeStore();
      const { result, rerender } = renderHook(
        (props) => useTutorSocket({ store: props.store, serverUrl: "ws://test/session" }),
        { initialProps: { store } }
      );

      const ref1 = result.current.sendAudioChunk;
      rerender({ store: makeStore() });
      const ref2 = result.current.sendAudioChunk;

      expect(ref1).toBe(ref2);
    });

    it("sendEndOfUtterance reference is stable across re-renders", async () => {
      const store = makeStore();
      const { result, rerender } = renderHook(
        (props) => useTutorSocket({ store: props.store, serverUrl: "ws://test/session" }),
        { initialProps: { store } }
      );

      const ref1 = result.current.sendEndOfUtterance;
      rerender({ store: makeStore() });
      const ref2 = result.current.sendEndOfUtterance;

      expect(ref1).toBe(ref2);
    });
  });
});
