import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useSpatialRealAvatar } from "./useSpatialRealAvatar";

const initializeSdk = vi.fn(async () => {});
const setSessionToken = vi.fn();
const cleanupSdk = vi.fn(async () => {});
const loadAvatar = vi.fn(async () => ({ id: "avatar-model" }));
const controllerStart = vi.fn(async () => {});
const controllerInitAudio = vi.fn(async () => {});
const controllerSend = vi.fn();
const controllerClose = vi.fn();
const controllerInterrupt = vi.fn();

let latestView: MockAvatarView | null = null;

class MockAvatarView {
  controller = {
    initializeAudioContext: controllerInitAudio,
    start: controllerStart,
    send: controllerSend,
    close: controllerClose,
    interrupt: controllerInterrupt,
    onConnectionState: null as ((state: "connected" | "disconnected" | "failed", error?: Error) => void) | null,
    onError: null as ((error: Error) => void) | null,
  };
  onFirstRendering?: () => void;
  private readonly canvas: HTMLCanvasElement;
  dispose = vi.fn();

  constructor(_avatar: unknown, container: HTMLElement) {
    this.canvas = document.createElement("canvas");
    container.appendChild(this.canvas);
    latestView = this;
  }

  getCanvas() {
    return this.canvas;
  }
}

vi.mock("@spatialwalk/avatarkit", () => ({
  AvatarSDK: {
    initialize: initializeSdk,
    setSessionToken,
    cleanup: cleanupSdk,
  },
  AvatarManager: {
    shared: {
      load: loadAvatar,
    },
  },
  AvatarView: MockAvatarView,
  Environment: { intl: "intl" },
  DrivingServiceMode: { sdk: "sdk" },
}));

describe("useSpatialRealAvatar", () => {
  beforeEach(() => {
    latestView = null;
    initializeSdk.mockClear();
    setSessionToken.mockClear();
    cleanupSdk.mockClear();
    loadAvatar.mockClear();
    controllerStart.mockClear();
    controllerInitAudio.mockClear();
    controllerSend.mockClear();
    controllerClose.mockClear();
    controllerInterrupt.mockClear();
  });

  it("does not become live until the first frame renders", async () => {
    const container = document.createElement("div");
    Object.defineProperty(container, "clientWidth", { value: 640 });
    Object.defineProperty(container, "clientHeight", { value: 480 });

    const { result } = renderHook(() => useSpatialRealAvatar());

    await act(async () => {
      await result.current.initialize("app-id", "session-token", "avatar-id", container);
    });

    expect(result.current.isConnected).toBe(false);
    expect(container.querySelector("canvas")).not.toBeNull();

    act(() => {
      latestView?.onFirstRendering?.();
    });

    expect(result.current.isConnected).toBe(true);
  });

  it("reattaches the existing canvas into a new container", async () => {
    const gettingReadyContainer = document.createElement("div");
    const lessonContainer = document.createElement("div");
    Object.defineProperty(gettingReadyContainer, "clientWidth", { value: 640 });
    Object.defineProperty(gettingReadyContainer, "clientHeight", { value: 480 });
    Object.defineProperty(lessonContainer, "clientWidth", { value: 320 });
    Object.defineProperty(lessonContainer, "clientHeight", { value: 240 });

    const { result } = renderHook(() => useSpatialRealAvatar());

    await act(async () => {
      await result.current.initialize("app-id", "session-token", "avatar-id", gettingReadyContainer);
    });

    const canvas = gettingReadyContainer.querySelector("canvas");
    expect(canvas).not.toBeNull();

    act(() => {
      result.current.attach(lessonContainer);
    });

    expect(gettingReadyContainer.querySelector("canvas")).toBeNull();
    expect(lessonContainer.querySelector("canvas")).toBe(canvas);
  });

  it("forwards audio only after start completes", async () => {
    const container = document.createElement("div");
    Object.defineProperty(container, "clientWidth", { value: 640 });
    Object.defineProperty(container, "clientHeight", { value: 480 });

    const { result } = renderHook(() => useSpatialRealAvatar());

    await act(async () => {
      await result.current.initialize("app-id", "session-token", "avatar-id", container);
    });

    act(() => {
      result.current.sendAudio(new ArrayBuffer(8), false);
    });
    expect(controllerSend).not.toHaveBeenCalled();

    await act(async () => {
      await result.current.start();
    });

    act(() => {
      result.current.sendAudio(new ArrayBuffer(8), true);
    });

    expect(controllerInitAudio).toHaveBeenCalledTimes(1);
    expect(controllerStart).toHaveBeenCalledTimes(1);
    expect(controllerSend).toHaveBeenCalledTimes(1);
  });
});
