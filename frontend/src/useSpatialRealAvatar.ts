/**
 * React hook for the SpatialReal AvatarKit Web SDK lifecycle.
 *
 * Parallel to useSimliWebRTC — manages initialization, connection,
 * audio forwarding, interrupt, and cleanup for SpatialReal's on-device
 * WebGL/WebGPU avatar rendering.
 *
 * Flow:
 *   1. Backend sends spatialreal_session_init { session_token, app_id, avatar_id }
 *   2. App calls initialize() → AvatarSDK.initialize, load avatar, create AvatarView
 *   3. User clicks "Start Lesson" → start() (must be in user gesture for AudioContext)
 *   4. TTS audio chunks arrive → sendAudio(pcmBytes, isEnd)
 *   5. Barge-in → interrupt()
 *   6. Session end / unmount → dispose()
 */

import { useRef, useCallback, useEffect, useState } from "react";
import type { ConnectionState } from "@spatialwalk/avatarkit";

/** Returns a compact timestamp prefix: [HH:MM:SS.mmm] */
function ts(): string {
  const now = new Date();
  return `[${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}:${String(now.getSeconds()).padStart(2, "0")}.${String(now.getMilliseconds()).padStart(3, "0")}]`;
}

export interface SpatialRealAvatarState {
  /** Whether the SpatialReal SDK is fully connected and rendering */
  isConnected: boolean;
  /** True during avatar download/initialization */
  isLoading: boolean;
  /** Current WebSocket connection state */
  connectionState: ConnectionState | null;
}

export interface SpatialRealAvatar extends SpatialRealAvatarState {
  /**
   * Initialize the SDK and load the avatar into a container element.
   * Called when spatialreal_session_init arrives from the backend.
   */
  initialize: (
    appId: string,
    sessionToken: string,
    avatarId: string,
    container: HTMLElement,
  ) => Promise<void>;

  /**
   * Start the avatar connection (WebSocket to SpatialReal cloud).
   * MUST be called from a user gesture (click handler) for AudioContext.
   */
  start: () => Promise<void>;

  /** Move the existing render canvas into a new container after a view swap. */
  attach: (container: HTMLElement) => void;

  /**
   * Forward a TTS audio chunk to SpatialReal for lip-sync.
   * @param pcmBytes Raw PCM Int16 16 kHz mono audio
   * @param isEnd    True for the last chunk of a response
   */
  sendAudio: (pcmBytes: ArrayBuffer, isEnd: boolean) => void;

  /** Interrupt current avatar playback (barge-in). */
  interrupt: () => void;

  /** Clean up all SDK resources. */
  dispose: () => void;
}

export function useSpatialRealAvatar(): SpatialRealAvatar {
  const [isConnected, setIsConnected] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [connectionState, setConnectionState] =
    useState<ConnectionState | null>(null);

  // Hold SDK objects in refs to avoid re-renders
  const avatarViewRef = useRef<unknown>(null);
  // Persistent host element passed to AvatarView. The SDK attaches its canvas
  // and ResizeObserver to this node, so we move the host between slots instead
  // of re-parenting the canvas directly.
  const containerRef = useRef<HTMLElement | null>(null);
  const controllerRef = useRef<unknown>(null);
  const initializedRef = useRef(false);
  // True after controller.start() resolves — audio can only be sent after this
  const startedRef = useRef(false);

  const mountContainer = useCallback((slot: HTMLElement): HTMLElement => {
    let host = containerRef.current;
    if (!host) {
      host = document.createElement("div");
      host.style.width = "100%";
      host.style.height = "100%";
      host.style.display = "flex";
      host.style.justifyContent = "center";
      host.style.alignItems = "center";
      host.style.position = "relative";
      containerRef.current = host;
    }
    if (host.parentElement !== slot) {
      slot.appendChild(host);
    }
    return host;
  }, []);

  const initialize = useCallback(
    async (
      appId: string,
      sessionToken: string,
      avatarId: string,
      container: HTMLElement,
    ) => {
      if (initializedRef.current) {
        console.debug(ts(), "[SpatialReal] Already initialized, skipping");
        return;
      }

      setIsLoading(true);
      console.debug(
        ts(),
        "[SpatialReal] Initializing SDK...",
        "appId:",
        appId,
        "avatarId:",
        avatarId,
      );

      try {
        // Dynamic import to avoid loading WASM when using Simli
        const {
          AvatarSDK,
          AvatarManager,
          AvatarView,
          Environment,
          DrivingServiceMode,
        } = await import("@spatialwalk/avatarkit");

        // 1. Initialize the SDK
        await AvatarSDK.initialize(appId, {
          environment: Environment.intl,
          drivingServiceMode: DrivingServiceMode.sdk,
          audioFormat: { channelCount: 1, sampleRate: 16000 },
        });

        // 2. Set session token
        AvatarSDK.setSessionToken(sessionToken);

        // 3. Load avatar model (may take several seconds for first load)
        console.debug(ts(), "[SpatialReal] Loading avatar model...");
        const avatar = await AvatarManager.shared.load(avatarId, (progress) => {
          console.debug(
            ts(),
            "[SpatialReal] Load progress:",
            progress.type,
            progress.progress ?? "",
          );
        });

        const host = mountContainer(container);

        const measuredWidth = host.clientWidth || container.clientWidth;
        const measuredHeight = host.clientHeight || container.clientHeight;

        // 4. Wait for the host container to have non-zero dimensions (layout must
        //    complete before WebGPU can create a swapchain).
        if (measuredWidth === 0 || measuredHeight === 0) {
          console.debug(ts(), "[SpatialReal] Container has zero dimensions, waiting for layout...");
          await new Promise<void>((resolve) => {
            const ro = new ResizeObserver((entries) => {
              for (const entry of entries) {
                if (entry.contentRect.width > 0 && entry.contentRect.height > 0) {
                  ro.disconnect();
                  clearTimeout(timeout);
                  resolve();
                  return;
                }
              }
            });
            // Safety timeout: if layout never fires within 3 s, proceed anyway
            // (better to attempt creation than hang forever).
            const timeout = setTimeout(() => {
              ro.disconnect();
              console.warn(ts(), "[SpatialReal] Container dimension wait timed out — proceeding");
              resolve();
            }, 3000);
            ro.observe(host);
          });
          console.debug(ts(), "[SpatialReal] Container laid out:", host.clientWidth || container.clientWidth, "x", host.clientHeight || container.clientHeight);
        }

        // 5. Create AvatarView (renders canvas inside container)
        const view = new AvatarView(avatar, host);
        avatarViewRef.current = view;

        const ctrl = view.controller;
        controllerRef.current = ctrl;

        // 5. Wire callbacks
        view.onFirstRendering = () => {
          console.debug(ts(), "[SpatialReal] First frame rendered — avatar live");
          setIsConnected(true);
          setIsLoading(false);
        };

        ctrl.onConnectionState = (
          state: ConnectionState,
          error?: Error,
        ) => {
          console.debug(
            ts(),
            "[SpatialReal] Connection state:",
            state,
            error ?? "",
          );
          setConnectionState(state);
          if (state === "disconnected" || state === "failed") {
            setIsConnected(false);
          }
        };

        ctrl.onError = (error: Error) => {
          console.error(ts(), "[SpatialReal] SDK error:", error);
        };

        initializedRef.current = true;
        console.debug(ts(), "[SpatialReal] Initialization complete");
      } catch (err) {
        console.error(ts(), "[SpatialReal] Initialization failed:", err);
        setIsLoading(false);
        throw err;
      }
    },
    [mountContainer],
  );

  const start = useCallback(async () => {
    const ctrl = controllerRef.current as {
      initializeAudioContext: () => Promise<void>;
      start: () => Promise<void>;
    } | null;
    if (!ctrl) {
      console.warn(
        ts(),
        "[SpatialReal] start() called before initialize()",
      );
      return;
    }

    console.debug(ts(), "[SpatialReal] Starting controller (user gesture)...");
    try {
      // initializeAudioContext MUST be called within a user gesture
      await ctrl.initializeAudioContext();
      await ctrl.start();
      startedRef.current = true;
      console.debug(ts(), "[SpatialReal] Controller started — audio forwarding enabled");
    } catch (err) {
      console.error(ts(), "[SpatialReal] start() failed:", err);
    }
  }, []);

  const attach = useCallback((container: HTMLElement) => {
    const host = containerRef.current;
    if (!host) {
      console.debug(ts(), "[SpatialReal] attach() skipped — no host yet");
      return;
    }
    if (host.parentElement === container) {
      return;
    }
    container.appendChild(host);
    console.debug(ts(), "[SpatialReal] Host attached to new container");
  }, []);

  const sendAudio = useCallback(
    (pcmBytes: ArrayBuffer, isEnd: boolean) => {
      // Don't forward audio until controller.start() has connected the service
      if (!startedRef.current) return;
      const ctrl = controllerRef.current as {
        send: (data: ArrayBuffer, end?: boolean) => string | null;
      } | null;
      if (!ctrl) return;
      ctrl.send(pcmBytes, isEnd);
    },
    [],
  );

  const interrupt = useCallback(() => {
    const ctrl = controllerRef.current as {
      interrupt: () => void;
    } | null;
    if (!ctrl) return;
    console.debug(ts(), "[SpatialReal] Interrupting playback");
    ctrl.interrupt();
  }, []);

  const dispose = useCallback(() => {
    console.debug(ts(), "[SpatialReal] Disposing...");
    const wasInitialized = initializedRef.current;
    try {
      const ctrl = controllerRef.current as { close: () => void } | null;
      ctrl?.close();
    } catch {
      /* best-effort */
    }
    try {
      const view = avatarViewRef.current as { dispose: () => void } | null;
      view?.dispose();
    } catch {
      /* best-effort */
    }
    // Only attempt SDK cleanup if we actually initialized it
    if (wasInitialized) {
      import("@spatialwalk/avatarkit")
        .then(({ AvatarSDK }) => AvatarSDK.cleanup())
        .catch(() => {/* best-effort */});
    }
    controllerRef.current = null;
    avatarViewRef.current = null;
    const host = containerRef.current;
    if (host?.parentElement) {
      host.parentElement.removeChild(host);
    }
    containerRef.current = null;
    initializedRef.current = false;
    startedRef.current = false;
    setIsConnected(false);
    setIsLoading(false);
    setConnectionState(null);
  }, []);

  // Clean up on unmount
  useEffect(() => {
    return () => dispose();
  }, [dispose]);

  return {
    isConnected,
    isLoading,
    connectionState,
    initialize,
    start,
    attach,
    sendAudio,
    interrupt,
    dispose,
  };
}
