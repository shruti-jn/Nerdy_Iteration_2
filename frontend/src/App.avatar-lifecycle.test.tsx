import * as React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { App } from "./App";

let mockAvatarProvider: "simli" | "spatialreal" = "simli";
let mockSessionKind: "start" | "restore" | null = "start";
let fakeStream: MediaStream;
let sendStartLessonSpy: ReturnType<typeof vi.fn>;
let sendContinueLessonSpy: ReturnType<typeof vi.fn>;
let reconnectSpy: ReturnType<typeof vi.fn>;
let disconnectSpy: ReturnType<typeof vi.fn>;
let spatialAttachSpy: ReturnType<typeof vi.fn>;
let spatialDisposeSpy: ReturnType<typeof vi.fn>;
let spatialInitializeSpy: ReturnType<typeof vi.fn>;
let spatialStartSpy: ReturnType<typeof vi.fn>;
let spatialSendAudioSpy: ReturnType<typeof vi.fn>;
let spatialConnectedSetter: ((value: boolean) => void) | null;
let simliRtcSendAudioSpy: ReturnType<typeof vi.fn>;
let simliConnected = false;
let startLessonHadAttachedLessonVideo = false;
let latestTutorSocketOpts:
  | {
      shouldPlayAudioChunk?: () => boolean;
      onAudioChunk?: (pcm: Uint8Array) => void;
      onAudioStreamComplete?: () => void;
    }
  | null;

vi.mock("./useAudioCapture", () => ({
  useAudioCapture: () => ({
    start: vi.fn(async () => {}),
    stop: vi.fn(),
    isActive: false,
  }),
}));

vi.mock("./useTutorSocket", () => ({
  useTutorSocket: (opts: {
    enabled?: boolean;
    onAvatarProvider?: (provider: "simli" | "spatialreal") => void;
    onSessionStart?: (kind: "start" | "restore") => void;
    onSpatialRealInit?: (sessionToken: string, appId: string, avatarId: string) => void;
    shouldPlayAudioChunk?: () => boolean;
    onAudioChunk?: (pcm: Uint8Array) => void;
    onAudioStreamComplete?: () => void;
  }) => {
    latestTutorSocketOpts = opts;
    const announcedRef = React.useRef(false);
    React.useEffect(() => {
      if (!opts.enabled || announcedRef.current) return;
      announcedRef.current = true;
      opts.onAvatarProvider?.(mockAvatarProvider);
      if (mockAvatarProvider === "spatialreal") {
        opts.onSpatialRealInit?.("session-token", "app-id", "avatar-id");
      }
      opts.onSessionStart?.(mockSessionKind === "restore" ? "restore" : "start");
    }, [opts.enabled, opts]);

    return {
      connect: vi.fn(),
      disconnect: disconnectSpy,
      reconnect: reconnectSpy,
      sendAudioChunk: vi.fn(),
      sendEndOfUtterance: vi.fn(),
      sendStartLesson: (...args: unknown[]) => {
        const lessonVideo = document.querySelector(".avatar-feed__video") as HTMLVideoElement | null;
        startLessonHadAttachedLessonVideo = lessonVideo?.srcObject === fakeStream;
        return sendStartLessonSpy(...args);
      },
      sendContinueLesson: sendContinueLessonSpy,
      sendBargeIn: vi.fn(),
      isConnected: true,
      sessionKind: mockSessionKind,
      get ws() {
        return { readyState: WebSocket.OPEN, send: vi.fn() } as unknown as WebSocket;
      },
    };
  },
}));

vi.mock("./useSimliWebRTC", () => ({
  useSimliWebRTC: (opts: { onStream: (stream: MediaStream) => void }) => ({
    connect: vi.fn(async () => {
      simliConnected = true;
      opts.onStream(fakeStream);
      return true;
    }),
    disconnect: vi.fn(),
    sendAudio: simliRtcSendAudioSpy,
    get isConnected() {
      return simliConnected;
    },
  }),
}));

vi.mock("./useSpatialRealAvatar", () => ({
  useSpatialRealAvatar: () => {
    const [isConnected, setIsConnected] = React.useState(false);

    React.useEffect(() => {
      spatialConnectedSetter = setIsConnected;
      return () => {
        spatialConnectedSetter = null;
      };
    }, []);

    return {
      isConnected,
      isLoading: false,
      connectionState: isConnected ? "connected" : null,
      initialize: spatialInitializeSpy,
      start: spatialStartSpy,
      attach: spatialAttachSpy,
      sendAudio: spatialSendAudioSpy,
      interrupt: vi.fn(),
      dispose: spatialDisposeSpy,
    };
  },
}));

describe("App avatar lifecycle", () => {
  beforeEach(() => {
    mockAvatarProvider = "simli";
    mockSessionKind = "start";
    fakeStream = { getTracks: () => [] } as unknown as MediaStream;
    sendStartLessonSpy = vi.fn();
    sendContinueLessonSpy = vi.fn();
    reconnectSpy = vi.fn();
    disconnectSpy = vi.fn();
    spatialAttachSpy = vi.fn();
    spatialDisposeSpy = vi.fn();
    spatialInitializeSpy = vi.fn(async () => {});
    spatialStartSpy = vi.fn(async () => {});
    spatialSendAudioSpy = vi.fn();
    spatialConnectedSetter = null;
    simliRtcSendAudioSpy = vi.fn();
    simliConnected = false;
    startLessonHadAttachedLessonVideo = false;
    latestTutorSocketOpts = null;

    vi.spyOn(window, "requestAnimationFrame").mockImplementation((cb: FrameRequestCallback) => {
      cb(0);
      return 1;
    });
    window.HTMLMediaElement.prototype.play = vi.fn(() => Promise.resolve());
    localStorage.clear();
    window.history.replaceState({}, "", "/");
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("keeps the Simli stream attached after Start Lesson", async () => {
    render(<App />);

    fireEvent.click(screen.getByRole("button", { name: /Start Photosynthesis/i }));

    const readyVideo = document.querySelector(".getting-ready__video") as HTMLVideoElement;
    expect(readyVideo).toBeTruthy();

    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 250));
    });

    expect(readyVideo.srcObject).toBe(fakeStream);

    Object.defineProperty(readyVideo, "videoWidth", { configurable: true, value: 640 });
    Object.defineProperty(readyVideo, "videoHeight", { configurable: true, value: 360 });

    await act(async () => {
      fireEvent.playing(readyVideo);
    });

    const startBtn = screen.getByRole("button", { name: "Start Lesson" });
    expect(startBtn).toBeEnabled();

    await act(async () => {
      fireEvent.click(startBtn);
    });

    const lessonVideo = document.querySelector(".avatar-feed__video") as HTMLVideoElement;
    expect(lessonVideo).toBeTruthy();
    expect(lessonVideo.srcObject).toBe(fakeStream);
    expect(startLessonHadAttachedLessonVideo).toBe(true);
    expect(sendStartLessonSpy).toHaveBeenCalledTimes(1);
  });

  it("reattaches the SpatialReal canvas after Start Lesson once the avatar is live", async () => {
    mockAvatarProvider = "spatialreal";

    render(<App />);

    fireEvent.click(screen.getByRole("button", { name: /Start Photosynthesis/i }));
    expect(screen.getByRole("button", { name: "Start Lesson" })).toBeDisabled();

    await act(async () => {
      spatialConnectedSetter?.(true);
    });

    const startBtn = screen.getByRole("button", { name: "Start Lesson" });
    expect(startBtn).toBeEnabled();

    await act(async () => {
      fireEvent.click(startBtn);
    });

    expect(spatialStartSpy).toHaveBeenCalledTimes(1);
    expect(spatialAttachSpy).toHaveBeenCalled();
    expect(sendStartLessonSpy).toHaveBeenCalledTimes(1);
  });

  it("routes SpatialReal tutor audio through the SDK and closes the audio round", async () => {
    mockAvatarProvider = "spatialreal";

    render(<App />);

    fireEvent.click(screen.getByRole("button", { name: /Start Photosynthesis/i }));

    await act(async () => {
      spatialConnectedSetter?.(true);
    });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Start Lesson" }));
    });

    expect(latestTutorSocketOpts?.shouldPlayAudioChunk?.()).toBe(false);

    const chunk = new Uint8Array([1, 2, 3, 4]);
    act(() => {
      latestTutorSocketOpts?.onAudioChunk?.(chunk);
      latestTutorSocketOpts?.onAudioStreamComplete?.();
    });

    expect(spatialSendAudioSpy).toHaveBeenCalledTimes(2);
    expect(spatialSendAudioSpy).toHaveBeenNthCalledWith(1, chunk.buffer, false);
    expect(spatialSendAudioSpy.mock.calls[1][0]).toBeInstanceOf(ArrayBuffer);
    expect(spatialSendAudioSpy.mock.calls[1][1]).toBe(true);
  });

  it("does not route Simli tutor audio through the browser sender in custom mode", async () => {
    mockAvatarProvider = "simli";

    render(<App />);

    fireEvent.click(screen.getByRole("button", { name: /Start Photosynthesis/i }));

    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 250));
    });

    act(() => {
      latestTutorSocketOpts?.onAudioChunk?.(new Uint8Array([4, 5, 6]));
    });

    expect(simliRtcSendAudioSpy).not.toHaveBeenCalled();
  });
  it("keeps the Simli stream attached when restarting a restored lesson", async () => {
    mockSessionKind = "restore";

    render(<App />);

    fireEvent.click(screen.getByRole("button", { name: /Start Photosynthesis/i }));

    const readyVideo = document.querySelector(".getting-ready__video") as HTMLVideoElement;
    expect(readyVideo).toBeTruthy();

    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 250));
    });

    Object.defineProperty(readyVideo, "videoWidth", { configurable: true, value: 640 });
    Object.defineProperty(readyVideo, "videoHeight", { configurable: true, value: 360 });

    await act(async () => {
      fireEvent.playing(readyVideo);
    });

    const startBtn = screen.getByRole("button", { name: "Start Lesson" });
    expect(startBtn).toBeEnabled();

    await act(async () => {
      fireEvent.click(startBtn);
    });

    const lessonVideo = document.querySelector(".avatar-feed__video") as HTMLVideoElement;
    expect(lessonVideo).toBeTruthy();
    expect(lessonVideo.srcObject).toBe(fakeStream);
    expect(startLessonHadAttachedLessonVideo).toBe(true);
    expect(reconnectSpy).not.toHaveBeenCalled();
    expect(sendStartLessonSpy).toHaveBeenCalledTimes(1);
  });

  it("restarts a restored SpatialReal lesson without reconnecting the avatar", async () => {
    mockAvatarProvider = "spatialreal";
    mockSessionKind = "restore";

    render(<App />);

    fireEvent.click(screen.getByRole("button", { name: /Start Photosynthesis/i }));

    await act(async () => {
      spatialConnectedSetter?.(true);
    });

    const startBtn = screen.getByRole("button", { name: "Start Lesson" });
    expect(startBtn).toBeEnabled();

    await act(async () => {
      fireEvent.click(startBtn);
    });

    expect(spatialDisposeSpy).not.toHaveBeenCalled();
    expect(reconnectSpy).not.toHaveBeenCalled();
    expect(spatialStartSpy).toHaveBeenCalledTimes(1);
    expect(sendStartLessonSpy).toHaveBeenCalledTimes(1);
  });
});
