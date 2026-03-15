import { useCallback, useEffect, useRef, useState } from "react";
import { TopBar } from "./components/TopBar";
import { ConversationHistory } from "./components/ConversationHistory";
import { AvatarFeed } from "./components/AvatarFeed";
import { TutorResponse } from "./components/TutorResponse";
import { BottomBar } from "./components/BottomBar";
import { TopicSelectView } from "./components/TopicSelectView";
import { GettingReadyView } from "./components/GettingReadyView";
import { CelebrationOverlay } from "./components/CelebrationOverlay";
import { useSessionStore } from "./useSessionStore";
import { useTutorSocket } from "./useTutorSocket";
import { useAudioCapture } from "./useAudioCapture";
import { useSimliWebRTC } from "./useSimliWebRTC";
import type { TopicId } from "./types";
import "./App.css";

const IS_MOCK = import.meta.env.VITE_MOCK === "true";

/** Compact timestamp: [HH:MM:SS.mmm] */
function ts(): string {
  const now = new Date();
  return `[${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}:${String(now.getSeconds()).padStart(2, "0")}.${String(now.getMilliseconds()).padStart(3, "0")}]`;
}

export function App() {
  const store = useSessionStore();

  // Ref for the Simli avatar <video> element (shared between GettingReady and Lesson views)
  const videoRef = useRef<HTMLVideoElement>(null);
  // Store the live MediaStream so it can be re-attached when the <video> element
  // changes across view transitions (GettingReady → Lesson unmounts/remounts the video).
  const streamRef = useRef<MediaStream | null>(null);

  // ── Avatar connection state (shimmer → slow → live) ─────────────────────
  const [avatarState, setAvatarState] = useState<import("./types").AvatarConnectionState>("connecting");
  const slowTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Guard against redundant Simli connect sequences (e.g. double onSessionStart
  // from WS reconnect or StrictMode). Set true when a connect starts; reset on
  // success, failure, back-navigation, or retry.
  const simliConnectingRef = useRef(false);

  // Start the slow timer when entering "getting-ready" view (not on page load)
  useEffect(() => {
    console.debug("[App] View changed to:", store.view);
    if (store.view !== "getting-ready") return;
    // Reset avatar state on each entry to getting-ready
    setAvatarState("connecting");
    console.debug("[App] Getting-ready: starting 8s slow timer");
    slowTimerRef.current = setTimeout(() => {
      console.debug("[App] Slow timer fired — avatar still not live");
      setAvatarState((s) => (s === "connecting" ? "slow" : s));
    }, 8000);
    return () => {
      if (slowTimerRef.current) clearTimeout(slowTimerRef.current);
    };
  }, [store.view]);

  // ── WebSocket connection to tutor-server ───────────────────────────────────
  // Only connect when we're past topic selection
  const wsEnabled = store.view === "getting-ready" || store.view === "lesson";

  const simliRtcRef = useRef<{ connect: () => Promise<boolean>; sendAudio: (data: Uint8Array) => void; readonly isConnected: boolean } | null>(null);

  const socket = useTutorSocket({
    store,
    topicId: store.topicId ?? undefined,
    enabled: wsEnabled,
    _useMock: IS_MOCK,
    onSessionStart: () => {
      // Skip if Simli is already connected or a connect sequence is in progress.
      // This prevents destroying a working PeerConnection when onSessionStart
      // fires a second time (e.g. WS auto-reconnect or StrictMode re-mount).
      if (simliConnectingRef.current || simliRtcRef.current?.isConnected) {
        console.debug("[App] onSessionStart — Simli already connected/connecting, skipping");
        return;
      }
      simliConnectingRef.current = true;
      console.debug("[App] onSessionStart — beginning Simli connect sequence");
      // Retry Simli connect with backoff — only retry when the WS isn't open
      // yet (connect() returns false). Once it returns true (SDP sent), stop
      // retrying and let ICE negotiation proceed undisturbed.
      const tryConnect = (attempt: number) => {
        if (attempt > 5) {
          console.error("[App] Simli connect failed after 5 attempts — no open WebSocket");
          simliConnectingRef.current = false;
          return;
        }
        const delay = attempt === 0 ? 200 : attempt * 500;
        setTimeout(() => {
          const rtc = simliRtcRef.current;
          if (!rtc) { console.debug("[App] Simli tryConnect: no RTC ref"); return; }
          console.debug(`[App] Simli connect attempt ${attempt + 1}, delay=${delay}ms`);
          rtc.connect().then((started) => {
            if (started) {
              console.debug(`[App] Simli connect attempt ${attempt + 1} — SDP offer sent`);
            } else {
              console.warn(`[App] Simli connect attempt ${attempt + 1} — WS not ready, retrying...`);
              tryConnect(attempt + 1);
            }
          }).catch(() => tryConnect(attempt + 1));
        }, delay);
      };
      tryConnect(0);
    },
    onAudioChunk: (pcm) => {
      // Forward TTS audio to Simli via DataChannel for avatar lip-sync
      simliRtcRef.current?.sendAudio(pcm);
    },
    onSimliError: (message) => {
      console.debug("[App] onSimliError:", message);
      simliConnectingRef.current = false;
      // Cancel the slow timer so "almost ready" text doesn't linger
      if (slowTimerRef.current) {
        clearTimeout(slowTimerRef.current);
        slowTimerRef.current = null;
      }
      setAvatarState("error");
      store.setError(message);
    },
  });

  // ── Microphone audio capture (PCM Int16 at 16 kHz) ─────────────────────────
  const audioCapture = useAudioCapture({
    onChunk: (chunk) => socket.sendAudioChunk(chunk),
    _useMock: IS_MOCK,
  });

  // ── Simli avatar WebRTC connection ─────────────────────────────────────────
  // Called by the <video> element's onPlaying handler (in GettingReadyView)
  // when actual video playback begins — NOT merely when the WebRTC track arrives.
  // Uses requestVideoFrameCallback (if available) to wait for the first real
  // decoded frame with non-zero dimensions before declaring the avatar "live".
  const handleVideoPlaying = useCallback(() => {
    const video = videoRef.current;
    if (!video) return;

    const markLive = () => {
      console.debug("[App] Avatar video confirmed live (%dx%d)", video.videoWidth, video.videoHeight);
      if (slowTimerRef.current) {
        clearTimeout(slowTimerRef.current);
        slowTimerRef.current = null;
      }
      setAvatarState("live");
    };

    // requestVideoFrameCallback fires when the browser is about to present a
    // decoded frame — more reliable than "playing" for WebRTC streams.
    // Use typeof check to avoid TS type narrowing issues with `in` operator.
    const rvfc = (video as HTMLVideoElement & { requestVideoFrameCallback?: (cb: () => void) => void }).requestVideoFrameCallback;
    if (typeof rvfc === "function") {
      rvfc.call(video, () => {
          if (video.videoWidth > 0 && video.videoHeight > 0) {
            markLive();
          } else {
            // Dimensions not ready yet — poll on each frame until they are
            const poll = () => {
              if (video.videoWidth > 0 && video.videoHeight > 0) {
                markLive();
              } else {
                requestAnimationFrame(poll);
              }
            };
            requestAnimationFrame(poll);
          }
        });
    } else {
      // Fallback: wait until videoWidth is non-zero (first decoded frame)
      if (video.videoWidth > 0 && video.videoHeight > 0) {
        markLive();
      } else {
        const poll = () => {
          if (video.videoWidth > 0 && video.videoHeight > 0) {
            markLive();
          } else {
            requestAnimationFrame(poll);
          }
        };
        requestAnimationFrame(poll);
      }
    }
  }, []);

  const simliRtc = useSimliWebRTC({
    getSignalingWs: () => socket.ws,
    _useMock: IS_MOCK,
    onClose: () => {
      console.debug("[App] Simli onClose — resetting connect guard");
      simliConnectingRef.current = false;
    },
    onStream: (stream) => {
      console.debug("[App] onStream called, tracks:", stream.getTracks().map(t => t.kind).join(", "));
      streamRef.current = stream;
      const video = videoRef.current;
      if (video) {
        if (video.srcObject !== stream) {
          video.srcObject = stream;
          console.debug("[App] Attached stream to video element");
        }
        video.play().catch((err) => {
          if (err.name !== "AbortError") {
            console.warn("[App] Video play() rejected:", err);
          }
        });
      } else {
        console.debug("[App] onStream: no video element yet — stream saved to ref for re-attach");
      }
      // Track received — cancel the slow timer since we're making progress,
      // but don't set "live" yet. That happens in handleVideoPlaying when
      // the <video> element actually starts rendering frames.
      if (slowTimerRef.current) {
        clearTimeout(slowTimerRef.current);
        slowTimerRef.current = null;
      }
    },
  });

  // Keep simliRtcRef in sync so the onSessionStart closure can call connect()
  useEffect(() => {
    simliRtcRef.current = simliRtc;
  }, [simliRtc]);

  // Re-attach the Simli MediaStream to the new <video> element after a view
  // transition (getting-ready → lesson). The old <video> is destroyed on
  // unmount; the new one in AvatarFeed mounts with no srcObject. ontrack
  // won't fire again, so we must re-attach from the saved streamRef.
  // Uses rAF to ensure the DOM has painted and the ref is assigned.
  useEffect(() => {
    if (store.view !== "lesson") return;
    const stream = streamRef.current;
    if (!stream) {
      console.debug("[App] View→lesson but no stream saved — avatar may not be connected");
      return;
    }
    const attach = () => {
      const video = videoRef.current;
      if (video && video.srcObject !== stream) {
        console.debug("[App] Re-attaching stream to new video element after view transition");
        video.srcObject = stream;
        video.play().catch((err) => {
          if (err.name !== "AbortError") {
            console.warn("[App] Video play() rejected on re-attach:", err);
          }
        });
      }
    };
    // Try immediately (ref should be set after commit), then retry on next frame
    // in case the ref assignment is deferred.
    attach();
    const rafId = requestAnimationFrame(attach);
    return () => cancelAnimationFrame(rafId);
  }, [store.view]);

  // ── View transition handlers ─────────────────────────────────────────────

  const handleSelectTopic = useCallback((id: TopicId, displayName: string) => {
    console.debug("[App] handleSelectTopic:", id, displayName);
    store.setTopic(id, displayName);
    store.setView("getting-ready");
  }, [store]);

  const handleBack = useCallback(() => {
    console.debug("[App] handleBack — disconnecting WS, resetting store");
    simliConnectingRef.current = false;
    socket.disconnect();
    store.reset();
    store.setView("topic-select");
  }, [socket, store]);

  const handleStartLesson = useCallback(() => {
    console.debug("[App] handleStartLesson — stream saved:", !!streamRef.current, "avatarState:", avatarState);
    store.setView("lesson");
    store.setMode("tutor-greeting");
    socket.sendStartLesson();
  }, [socket, store, avatarState]);

  // ── Mic handlers ───────────────────────────────────────────────────────────

  const handleMicPress = useCallback(() => {
    console.log(ts(), "[Mic] 🎙️ MIC PRESS — mode:", store.mode, "sessionComplete:", store.sessionComplete);
    if (store.mode !== "idle") { console.log(ts(), "[Mic] Ignored — mode is", store.mode); return; }
    // Block new utterances if the session is complete
    if (store.sessionComplete) { console.log(ts(), "[Mic] Ignored — session complete"); return; }
    store.setError(null); // clear any previous error
    store.setMode("student-speaking");
    store.addStudentUtterance("…"); // placeholder — updated by streaming partials
    console.log(ts(), "[Mic] Starting audio capture...");
    audioCapture.start().then(() => {
      console.log(ts(), "[Mic] Audio capture started successfully");
    }).catch((err: unknown) => {
      console.error(ts(), "[Mic] Failed to start audio capture:", err);
      store.removeLastStudentUtterance(); // remove stale "…" placeholder
      store.setMode("idle"); // roll back so the button isn't stuck

      // Surface a human-readable error so the user knows what went wrong
      const msg = err instanceof DOMException ? err.message : String(err);
      if (msg.includes("Permission denied") || msg.includes("NotAllowedError")) {
        store.setError("Microphone permission denied. Please allow mic access in your browser and reload.");
      } else if (msg.includes("NotFoundError") || msg.includes("Requested device not found")) {
        store.setError("No microphone found. Please connect a microphone and try again.");
      } else {
        store.setError(`Mic error: ${msg}`);
      }
    });
  }, [store, audioCapture]);

  const handleMicRelease = useCallback(() => {
    console.log(ts(), "[Mic] 🛑 MIC RELEASE — mode:", store.mode, "audioActive:", audioCapture.isActive);
    if (store.mode !== "student-speaking") { console.log(ts(), "[Mic] Ignored — mode is", store.mode); return; }
    const wasActive = audioCapture.isActive;
    audioCapture.stop();
    console.log(ts(), "[Mic] Audio capture stopped, wasActive:", wasActive);
    store.setMode("idle");
    if (!wasActive) {
      console.log(ts(), "[Mic] Audio was not active — removing placeholder utterance");
      store.removeLastStudentUtterance();
      return;
    }
    console.log(ts(), "[Mic] Sending end_of_utterance to backend");
    socket.sendEndOfUtterance();
  }, [store, audioCapture, socket]);

  const handleAvatarRetry = useCallback(() => {
    simliConnectingRef.current = false;
    store.setError(null);
    setAvatarState("connecting");
    slowTimerRef.current = setTimeout(() => {
      setAvatarState((s) => (s === "connecting" ? "slow" : s));
    }, 8000);
    simliRtcRef.current?.connect().then((started) => {
      if (!started) {
        console.warn("[App] Avatar retry — WS not ready");
        setAvatarState("error");
        store.setError("Could not reach server. Please refresh the page.");
      }
    }).catch(() => {
      setAvatarState("error");
      store.setError("Retry failed. Please refresh the page.");
    });
  }, [store]);

  const handleBargeIn = useCallback(() => {
    console.log(ts(), "[Mic] ⚡ BARGE-IN");
    socket.sendBargeIn();
    store.bargeIn();
  }, [socket, store]);

  // ── Keyboard shortcut: Space bar to hold-to-speak (lesson view only) ──────
  useEffect(() => {
    if (store.view !== "lesson") return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.code === "Space" && e.target === document.body && store.mode === "idle") {
        e.preventDefault();
        handleMicPress();
      }
    };
    const onKeyUp = (e: KeyboardEvent) => {
      if (e.code === "Space" && store.mode === "student-speaking") {
        e.preventDefault();
        handleMicRelease();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keyup", onKeyUp);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("keyup", onKeyUp);
    };
  }, [store.view, store.mode, handleMicPress, handleMicRelease]);

  // ── View routing ──────────────────────────────────────────────────────────

  if (store.view === "topic-select") {
    return <TopicSelectView onSelectTopic={handleSelectTopic} />;
  }

  if (store.view === "getting-ready") {
    return (
      <GettingReadyView
        topic={store.topic}
        avatarState={avatarState}
        wsConnected={socket.isConnected}
        videoRef={videoRef as React.RefObject<HTMLVideoElement>}
        onBack={handleBack}
        onStart={handleStartLesson}
        onVideoPlaying={handleVideoPlaying}
      />
    );
  }

  // ── View 3: Lesson ────────────────────────────────────────────────────────

  return (
    <div className={`app app--${store.mode}`}>
      <TopBar store={store} />

      <main className="app__main">
        <div className="app__col app__col--left">
          <ConversationHistory history={store.history} />
        </div>

        <div className="app__col app__col--center">
          <AvatarFeed mode={store.mode} videoRef={videoRef} avatarState={avatarState} onRetry={handleAvatarRetry} />
        </div>

        <div className="app__col app__col--right">
          <TutorResponse mode={store.mode} streamingWords={store.streamingWords} />
        </div>
      </main>

      {store.sessionComplete && (
        <CelebrationOverlay
          topic={store.topic}
          turnCount={store.turnNumber}
          totalTurns={store.totalTurns}
          onTryAnother={handleBack}
        />
      )}

      {store.error && (
        <div className="app__error-banner" role="alert">
          {store.error}
        </div>
      )}

      <BottomBar
        mode={store.mode}
        latencyMs={store.latencyMs}
        onMicPress={handleMicPress}
        onMicRelease={handleMicRelease}
        onBargeIn={handleBargeIn}
      />
    </div>
  );
}
