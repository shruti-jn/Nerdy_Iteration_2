/**
 * End-to-end integration test for the mic -> audio capture -> WebSocket pipeline.
 *
 * Tests the full user flow:
 *   Topic select -> Getting ready -> Lesson -> Press mic -> getUserMedia ->
 *   AudioWorklet -> PCM chunks -> WS.send() -> release mic -> end_of_utterance
 *
 * This test renders the full <App> with mocked browser APIs and verifies
 * that the pipeline works end-to-end without audio being silently dropped.
 *
 * Since App now starts on topic-select view, these tests navigate through
 * topic selection and getting-ready before reaching the lesson view.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { App } from "./App";

// ── Mock browser APIs ──────────────────────────────────────────────────────

let mockWsInstances: MockWebSocket[];
let mockWorkletOnMessage: ((e: { data: ArrayBuffer }) => void) | null;
let getUserMediaCalls: number;

class MockWebSocket {
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
  sentMessages: unknown[] = [];

  send = vi.fn((data: unknown) => {
    this.sentMessages.push(data);
  });
  close = vi.fn(() => {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.();
  });

  constructor(url: string) {
    this.url = url;
    mockWsInstances.push(this);
    // Auto-open
    queueMicrotask(() => {
      if (this.readyState === MockWebSocket.CONNECTING) {
        this.readyState = MockWebSocket.OPEN;
        this.onopen?.();
        // Server sends session_start immediately
        queueMicrotask(() => {
          this.onmessage?.({
            data: JSON.stringify({ type: "session_start", session_id: "test-session" }),
          });
        });
      }
    });
  }
}

function setupAllMocks() {
  mockWsInstances = [];
  mockWorkletOnMessage = null;
  getUserMediaCalls = 0;

  // @ts-expect-error — mock
  globalThis.WebSocket = MockWebSocket;
  (globalThis.WebSocket as unknown as Record<string, number>).OPEN = 1;
  (globalThis.WebSocket as unknown as Record<string, number>).CONNECTING = 0;
  (globalThis.WebSocket as unknown as Record<string, number>).CLOSED = 3;

  // Mock getUserMedia
  const trackStop = vi.fn();
  const mockStream = { getTracks: () => [{ stop: trackStop }] };
  Object.defineProperty(globalThis.navigator, "mediaDevices", {
    value: {
      getUserMedia: vi.fn(async () => {
        getUserMediaCalls++;
        return mockStream;
      }),
    } as unknown as MediaDevices,
    writable: true,
    configurable: true,
  });

  // Mock AudioContext + AudioWorklet
  // @ts-expect-error — mock
  globalThis.AudioContext = vi.fn(() => ({
    audioWorklet: {
      addModule: vi.fn().mockResolvedValue(undefined),
    },
    createMediaStreamSource: vi.fn(() => ({
      connect: vi.fn(),
    })),
    createScriptProcessor: vi.fn(),
    createBuffer: vi.fn(() => ({ getChannelData: () => new Float32Array(0) })),
    createBufferSource: vi.fn(() => ({
      connect: vi.fn(),
      start: vi.fn(),
      buffer: null,
      onended: null,
    })),
    decodeAudioData: vi.fn(),
    close: vi.fn().mockResolvedValue(undefined),
    destination: {},
    sampleRate: 16000,
    state: "running",
  }));

  // @ts-expect-error — mock
  globalThis.AudioWorkletNode = vi.fn(() => ({
    port: {
      set onmessage(handler: ((e: { data: ArrayBuffer }) => void) | null) {
        mockWorkletOnMessage = handler;
      },
      get onmessage() {
        return mockWorkletOnMessage;
      },
    },
    disconnect: vi.fn(),
  }));

  // Mock RTCPeerConnection (used by useSimliWebRTC)
  // @ts-expect-error — mock
  globalThis.RTCPeerConnection = vi.fn(() => ({
    createOffer: vi.fn().mockResolvedValue({ sdp: "mock-sdp", type: "offer" }),
    setLocalDescription: vi.fn(),
    setRemoteDescription: vi.fn(),
    close: vi.fn(),
    signalingState: "stable",
    addTransceiver: vi.fn(),
    createDataChannel: vi.fn(() => ({
      readyState: "open",
      send: vi.fn(),
      close: vi.fn(),
      onopen: null,
      onclose: null,
    })),
    onicecandidate: null,
    ontrack: null,
  }));
}

/**
 * Navigate from topic-select through getting-ready to the lesson view.
 *
 * Uses fake timers to fast-forward past the 15s avatar fallback timeout,
 * then clicks "Start Lesson" once it becomes enabled.
 */
async function navigateToLessonView() {
  // 1. Select a topic — transitions to getting-ready view
  const photoBtn = screen.getByRole("button", { name: /Start Photosynthesis/i });
  await act(async () => {
    fireEvent.click(photoBtn);
  });

  // 2. Wait for WS to connect (microtasks settle)
  await act(async () => {
    await new Promise((r) => setTimeout(r, 50));
  });

  // 3. Advance timers past the 15s avatar fallback so "Start Lesson" becomes enabled
  //    The getting-ready view has a 15s timer for showFallback and an 8s timer for slow state.
  await act(async () => {
    vi.advanceTimersByTime(16_000);
  });

  // 4. Click "Start Lesson" (enabled via wsConnected && showFallback)
  const startBtn = screen.getByRole("button", { name: /Start Lesson/i });
  await act(async () => {
    fireEvent.click(startBtn);
  });

  // 5. Flush remaining microtasks
  await act(async () => {
    await new Promise((r) => setTimeout(r, 50));
  });

  await vi.waitFor(() => {
    expect((window as unknown as Record<string, unknown>).__tutorWs).toBeDefined();
  });
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  setupAllMocks();
  localStorage.clear();
  window.history.replaceState({}, "", "/");
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

// ── Tests ──────────────────────────────────────────────────────────────────

describe.skip("Mic -> WebSocket E2E pipeline", () => {
  it("full flow: press mic -> audio chunks sent over WS -> release sends end_of_utterance", async () => {
    // 1. Render the app — starts on topic-select view
    await act(async () => {
      render(<App />);
    });

    // 2. Navigate to lesson view
    await navigateToLessonView();

    const ws = (window as unknown as Record<string, unknown>).__tutorWs as MockWebSocket;
    expect(ws).toBeDefined();
    expect(ws.readyState).toBe(1); // OPEN

    // 3. Simulate greeting completion so mode returns to idle and mic is enabled.
    //    The lesson view starts in tutor-greeting mode; greeting_complete sets idle.
    await act(async () => {
      ws.onmessage?.({
        data: JSON.stringify({ type: "greeting_complete" }),
      });
    });
    await act(async () => {
      await new Promise((r) => setTimeout(r, 50));
    });

    // 4. Press the mic button (mousedown = start recording)
    const micBtn = screen.getByRole("button", { name: /hold to speak/i });
    await act(async () => {
      fireEvent.mouseDown(micBtn);
    });

    // Wait for getUserMedia + worklet setup
    await act(async () => {
      await new Promise((r) => setTimeout(r, 50));
    });

    expect(getUserMediaCalls).toBe(1);

    // 5. Simulate the AudioWorklet posting PCM chunks
    expect(mockWorkletOnMessage).not.toBeNull();

    const chunk1 = new ArrayBuffer(8192);
    const chunk2 = new ArrayBuffer(8192);
    act(() => {
      mockWorkletOnMessage!({ data: chunk1 });
      mockWorkletOnMessage!({ data: chunk2 });
    });

    // Chunks should have been sent as binary over the WS
    const binarySends = ws.sentMessages.filter((m) => m instanceof ArrayBuffer);
    expect(binarySends).toHaveLength(2);

    // 6. Release the mic button (mouseup = stop recording + send end_of_utterance)
    await act(async () => {
      fireEvent.mouseUp(micBtn);
    });

    const jsonSends = ws.sentMessages
      .filter((m): m is string => typeof m === "string")
      .map((m) => JSON.parse(m));

    const eou = jsonSends.find((m) => m.type === "end_of_utterance");
    expect(eou).toBeDefined();
  });

  it("mic failure does NOT produce phantom utterance or end_of_utterance", async () => {
    // Override getUserMedia to fail
    Object.defineProperty(globalThis.navigator, "mediaDevices", {
      value: {
        getUserMedia: vi.fn().mockRejectedValue(
          new DOMException("Permission denied", "NotAllowedError")
        ),
      } as unknown as MediaDevices,
      writable: true,
      configurable: true,
    });

    await act(async () => {
      render(<App />);
    });

    await navigateToLessonView();

    const ws = (window as unknown as Record<string, unknown>).__tutorWs as MockWebSocket;
    expect(ws).toBeDefined();

    // Simulate greeting completion so mode returns to idle and mic is enabled
    await act(async () => {
      ws.onmessage?.({
        data: JSON.stringify({ type: "greeting_complete" }),
      });
    });
    await act(async () => {
      await new Promise((r) => setTimeout(r, 50));
    });

    ws.sentMessages.length = 0; // clear any setup messages

    // Press and release mic
    const micBtn = screen.getByRole("button", { name: /hold to speak/i });
    await act(async () => {
      fireEvent.mouseDown(micBtn);
    });
    await act(async () => {
      await new Promise((r) => setTimeout(r, 50));
    });
    await act(async () => {
      fireEvent.mouseUp(micBtn);
    });

    // No audio chunks or end_of_utterance should have been sent
    const endMsgs = ws.sentMessages
      .filter((m): m is string => typeof m === "string")
      .filter((m) => m.includes("end_of_utterance"));
    expect(endMsgs).toHaveLength(0);

    // Error banner should be visible
    expect(screen.getByRole("alert")).toHaveTextContent(/microphone permission denied/i);
  });

  it("quick click (press + immediate release) resets button to idle -- not stuck red", async () => {
    // Make getUserMedia hang forever so start() is guaranteed still pending when
    // mouseup fires. This means isActive=false on release, which is the exact
    // code path fixed in handleMicRelease (mode must still reset to idle).
    Object.defineProperty(globalThis.navigator, "mediaDevices", {
      value: { getUserMedia: vi.fn(() => new Promise(() => {})) },
      writable: true,
      configurable: true,
    });

    await act(async () => { render(<App />); });

    await navigateToLessonView();

    const ws = (window as unknown as Record<string, unknown>).__tutorWs as MockWebSocket;

    // Simulate greeting completion so mode returns to idle and mic is enabled
    await act(async () => {
      ws.onmessage?.({
        data: JSON.stringify({ type: "greeting_complete" }),
      });
    });
    await act(async () => {
      await new Promise((r) => setTimeout(r, 50));
    });

    const micBtn = screen.getByRole("button", { name: /hold to speak/i });

    // Press and immediately release
    act(() => { fireEvent.mouseDown(micBtn); });
    act(() => { fireEvent.mouseUp(micBtn); });

    // Button must be back to idle — not stuck red in "student-speaking" state
    expect(screen.getByRole("button", { name: /hold to speak/i })).toBeInTheDocument();
    expect(screen.queryByText(/release to send/i)).not.toBeInTheDocument();
  });

  it("WebSocket is NOT recreated when mic is pressed (state change stability)", async () => {
    await act(async () => {
      render(<App />);
    });

    await navigateToLessonView();

    const ws = (window as unknown as Record<string, unknown>).__tutorWs as MockWebSocket;

    // Simulate greeting completion so mode returns to idle and mic is enabled
    await act(async () => {
      ws.onmessage?.({
        data: JSON.stringify({ type: "greeting_complete" }),
      });
    });
    await act(async () => {
      await new Promise((r) => setTimeout(r, 50));
    });

    const wsBefore = (window as unknown as Record<string, unknown>).__tutorWs;
    const micBtn = screen.getByRole("button", { name: /hold to speak/i });

    // Press and release the mic — triggers mode changes (idle -> student-speaking -> idle)
    await act(async () => {
      fireEvent.mouseDown(micBtn);
    });
    await act(async () => {
      await new Promise((r) => setTimeout(r, 50));
    });
    await act(async () => {
      fireEvent.mouseUp(micBtn);
    });

    // The active WebSocket instance should stay the same through mode changes
    expect((window as unknown as Record<string, unknown>).__tutorWs).toBe(wsBefore);
  });
});
