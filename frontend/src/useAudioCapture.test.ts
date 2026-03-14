/**
 * Tests for useAudioCapture hook.
 *
 * Verifies:
 * - getUserMedia is called with correct constraints
 * - AudioWorklet path works and delivers chunks via onChunk
 * - ScriptProcessorNode fallback when AudioWorklet fails
 * - stop() cleans up all resources
 * - start() is idempotent (no double-start)
 * - getUserMedia failure surfaces correctly (doesn't swallow errors)
 * - Callback stability: start/stop don't change across renders
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useAudioCapture } from "./useAudioCapture";

// ── Mock infrastructure ────────────────────────────────────────────────────

let mockStream: {
  getTracks: ReturnType<typeof vi.fn>;
};
let mockAudioContext: {
  audioWorklet: { addModule: ReturnType<typeof vi.fn> };
  createMediaStreamSource: ReturnType<typeof vi.fn>;
  createScriptProcessor: ReturnType<typeof vi.fn>;
  close: ReturnType<typeof vi.fn>;
  destination: {};
  sampleRate: number;
};
let mockWorkletNode: {
  port: { onmessage: ((e: { data: ArrayBuffer }) => void) | null };
  disconnect: ReturnType<typeof vi.fn>;
};
let mockScriptNode: {
  onaudioprocess: ((ev: unknown) => void) | null;
  connect: ReturnType<typeof vi.fn>;
  disconnect: ReturnType<typeof vi.fn>;
};
let mockSourceNode: {
  connect: ReturnType<typeof vi.fn>;
};

function setupMocks(opts?: { workletFails?: boolean; getUserMediaFails?: boolean }) {
  const trackStop = vi.fn();
  mockStream = {
    getTracks: vi.fn(() => [{ stop: trackStop }]),
  };

  mockWorkletNode = {
    port: { onmessage: null },
    disconnect: vi.fn(),
  };

  mockScriptNode = {
    onaudioprocess: null,
    connect: vi.fn(),
    disconnect: vi.fn(),
  };

  mockSourceNode = {
    connect: vi.fn(),
  };

  mockAudioContext = {
    audioWorklet: {
      addModule: opts?.workletFails
        ? vi.fn().mockRejectedValue(new Error("Worklet load failed"))
        : vi.fn().mockResolvedValue(undefined),
    },
    createMediaStreamSource: vi.fn(() => mockSourceNode),
    createScriptProcessor: vi.fn(() => mockScriptNode),
    close: vi.fn().mockResolvedValue(undefined),
    destination: {},
    sampleRate: 16000,
  };

  // @ts-expect-error — mock
  globalThis.AudioContext = vi.fn(() => mockAudioContext);
  // @ts-expect-error — mock
  globalThis.AudioWorkletNode = vi.fn(() => mockWorkletNode);

  const getUserMedia = opts?.getUserMediaFails
    ? vi.fn().mockRejectedValue(new DOMException("Permission denied", "NotAllowedError"))
    : vi.fn().mockResolvedValue(mockStream);

  Object.defineProperty(globalThis.navigator, "mediaDevices", {
    value: { getUserMedia } as unknown as MediaDevices,
    writable: true,
    configurable: true,
  });
}

beforeEach(() => {
  setupMocks();
});

afterEach(() => {
  // Use clearAllMocks instead of restoreAllMocks — restoreAllMocks resets
  // mockResolvedValue implementations before React's cleanup unmounts the
  // component, causing AudioContext.close() to return undefined.
  vi.clearAllMocks();
});

// ── Tests ──────────────────────────────────────────────────────────────────

describe("useAudioCapture", () => {
  it("calls getUserMedia with correct audio constraints on start()", async () => {
    const onChunk = vi.fn();
    const { result } = renderHook(() => useAudioCapture({ onChunk }));

    await act(async () => {
      await result.current.start();
    });

    expect(navigator.mediaDevices.getUserMedia).toHaveBeenCalledWith({
      audio: {
        channelCount: 1,
        sampleRate: 16000,
        echoCancellation: true,
        noiseSuppression: true,
      },
    });
  });

  it("loads AudioWorklet and connects source → worklet", async () => {
    const onChunk = vi.fn();
    const { result } = renderHook(() => useAudioCapture({ onChunk }));

    await act(async () => {
      await result.current.start();
    });

    expect(mockAudioContext.audioWorklet.addModule).toHaveBeenCalledWith("/pcm-processor.js");
    expect(mockSourceNode.connect).toHaveBeenCalledWith(mockWorkletNode);
    expect(result.current.isActive).toBe(true);
  });

  it("delivers PCM chunks via onChunk callback when worklet posts messages", async () => {
    const onChunk = vi.fn();
    const { result } = renderHook(() => useAudioCapture({ onChunk }));

    await act(async () => {
      await result.current.start();
    });

    // Simulate worklet posting a PCM chunk
    const fakeChunk = new ArrayBuffer(8192);
    mockWorkletNode.port.onmessage!({ data: fakeChunk });

    expect(onChunk).toHaveBeenCalledTimes(1);
    expect(onChunk).toHaveBeenCalledWith(fakeChunk);
  });

  it("falls back to ScriptProcessorNode when AudioWorklet fails", async () => {
    setupMocks({ workletFails: true });
    const onChunk = vi.fn();
    const { result } = renderHook(() => useAudioCapture({ onChunk }));

    await act(async () => {
      await result.current.start();
    });

    // Should have used ScriptProcessor instead
    expect(mockAudioContext.createScriptProcessor).toHaveBeenCalledWith(4096, 1, 1);
    expect(mockScriptNode.connect).toHaveBeenCalledWith(mockAudioContext.destination);
    expect(result.current.isActive).toBe(true);
  });

  it("ScriptProcessor fallback delivers PCM chunks via onChunk", async () => {
    setupMocks({ workletFails: true });
    const onChunk = vi.fn();
    const { result } = renderHook(() => useAudioCapture({ onChunk }));

    await act(async () => {
      await result.current.start();
    });

    // Simulate ScriptProcessor firing an audioprocess event
    const inputBuffer = { getChannelData: () => new Float32Array(4096).fill(0.5) };
    mockScriptNode.onaudioprocess!({ inputBuffer });

    expect(onChunk).toHaveBeenCalledTimes(1);
    const chunk = onChunk.mock.calls[0][0] as ArrayBuffer;
    expect(chunk.byteLength).toBe(4096 * 2); // Int16 = 2 bytes per sample
  });

  it("stop() disconnects worklet, closes context, and stops tracks", async () => {
    const onChunk = vi.fn();
    const { result } = renderHook(() => useAudioCapture({ onChunk }));

    await act(async () => {
      await result.current.start();
    });
    expect(result.current.isActive).toBe(true);

    act(() => {
      result.current.stop();
    });

    expect(mockWorkletNode.disconnect).toHaveBeenCalled();
    expect(mockAudioContext.close).toHaveBeenCalled();
    expect(mockStream.getTracks()[0].stop).toHaveBeenCalled();
    expect(result.current.isActive).toBe(false);
  });

  it("start() is idempotent — second call is a no-op when already active", async () => {
    const onChunk = vi.fn();
    const { result } = renderHook(() => useAudioCapture({ onChunk }));

    await act(async () => {
      await result.current.start();
    });
    // Reset the mock call count
    (navigator.mediaDevices.getUserMedia as ReturnType<typeof vi.fn>).mockClear();

    await act(async () => {
      await result.current.start();
    });

    expect(navigator.mediaDevices.getUserMedia).not.toHaveBeenCalled();
  });

  it("getUserMedia failure rejects the promise (not swallowed)", async () => {
    setupMocks({ getUserMediaFails: true });
    const onChunk = vi.fn();
    const { result } = renderHook(() => useAudioCapture({ onChunk }));

    await expect(
      act(async () => {
        await result.current.start();
      })
    ).rejects.toThrow("Permission denied");

    expect(result.current.isActive).toBe(false);
  });

  it("start() callback reference is stable across re-renders (no unnecessary recreations)", () => {
    const onChunk = vi.fn();
    const { result, rerender } = renderHook(
      (props) => useAudioCapture({ onChunk: props.onChunk }),
      { initialProps: { onChunk } }
    );

    const startRef1 = result.current.start;
    const stopRef1 = result.current.stop;

    // Re-render with a new onChunk function (simulates parent re-render)
    rerender({ onChunk: vi.fn() });

    const startRef2 = result.current.start;
    const stopRef2 = result.current.stop;

    // start/stop must be the same function reference — if they change,
    // downstream useCallbacks and useEffects re-run, causing the bugs we fixed
    expect(startRef1).toBe(startRef2);
    expect(stopRef1).toBe(stopRef2);
  });

  it("onChunk always calls the latest callback (not a stale closure)", async () => {
    const onChunk1 = vi.fn();
    const onChunk2 = vi.fn();

    const { result, rerender } = renderHook(
      (props) => useAudioCapture({ onChunk: props.onChunk }),
      { initialProps: { onChunk: onChunk1 } }
    );

    await act(async () => {
      await result.current.start();
    });

    // Simulate parent re-render with new callback
    rerender({ onChunk: onChunk2 });

    // Now fire a chunk — should go to onChunk2, not onChunk1
    const fakeChunk = new ArrayBuffer(8192);
    mockWorkletNode.port.onmessage!({ data: fakeChunk });

    expect(onChunk1).not.toHaveBeenCalled();
    expect(onChunk2).toHaveBeenCalledWith(fakeChunk);
  });

  it("stop() called while addModule is pending — no nodes created, isActive stays false", async () => {
    // Control when addModule resolves so we can call stop() in between.
    // Use async act to flush getUserMedia first, ensuring addModule is actually called
    // before we invoke stop(). Without the flush, resolveAddModule would be unset.
    let resolveAddModule!: () => void;
    mockAudioContext.audioWorklet.addModule = vi.fn(
      () => new Promise<void>((r) => { resolveAddModule = r; })
    );

    const onChunk = vi.fn();
    const { result } = renderHook(() => useAudioCapture({ onChunk }));

    // Launch start() and flush past getUserMedia so addModule gets called
    let startPromise!: Promise<void>;
    await act(async () => {
      startPromise = result.current.start();
      await new Promise((r) => setTimeout(r, 0)); // flush getUserMedia microtask
    });

    // addModule is now pending — resolveAddModule is set
    expect(resolveAddModule).toBeDefined();

    // Call stop() — this closes and nulls the AudioContext
    act(() => { result.current.stop(); });

    // Resolve addModule — start() hits contextRef guard and returns cleanly
    await act(async () => {
      resolveAddModule();
      await startPromise;
    });

    // No AudioWorkletNode should have been constructed
    expect(globalThis.AudioWorkletNode).not.toHaveBeenCalled();
    // isActive must remain false — start() bailed before setting it
    expect(result.current.isActive).toBe(false);
  });

  it("stop() called while addModule is pending (worklet fails) — ScriptProcessor fallback also skipped", async () => {
    let rejectAddModule!: (err: Error) => void;
    mockAudioContext.audioWorklet.addModule = vi.fn(
      () => new Promise<void>((_, r) => { rejectAddModule = r; })
    );

    const onChunk = vi.fn();
    const { result } = renderHook(() => useAudioCapture({ onChunk }));

    let startPromise!: Promise<void>;
    await act(async () => {
      startPromise = result.current.start();
      await new Promise((r) => setTimeout(r, 0));
    });

    expect(rejectAddModule).toBeDefined();

    act(() => { result.current.stop(); });

    await act(async () => {
      rejectAddModule(new Error("Worklet failed"));
      await startPromise;
    });

    // Neither AudioWorkletNode nor ScriptProcessor should have been created
    expect(globalThis.AudioWorkletNode).not.toHaveBeenCalled();
    expect(mockAudioContext.createScriptProcessor).not.toHaveBeenCalled();
    expect(result.current.isActive).toBe(false);
  });

  it("_useMock skips getUserMedia entirely", async () => {
    const onChunk = vi.fn();
    const { result } = renderHook(() => useAudioCapture({ onChunk, _useMock: true }));

    await act(async () => {
      await result.current.start();
    });

    expect(navigator.mediaDevices.getUserMedia).not.toHaveBeenCalled();
    expect(result.current.isActive).toBe(true);
  });
});
