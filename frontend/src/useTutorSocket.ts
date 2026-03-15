import { useRef, useCallback, useEffect } from "react";
import type { SessionStore } from "./types";

/** Returns a compact timestamp prefix: [HH:MM:SS.mmm] */
function ts(): string {
  const now = new Date();
  const hh = String(now.getHours()).padStart(2, "0");
  const mm = String(now.getMinutes()).padStart(2, "0");
  const ss = String(now.getSeconds()).padStart(2, "0");
  const ms = String(now.getMilliseconds()).padStart(3, "0");
  return `[${hh}:${mm}:${ss}.${ms}]`;
}

export interface TutorSocketOptions {
  /** WebSocket server URL. Defaults to ws://localhost:3001/session */
  serverUrl?: string;
  store: SessionStore;
  /** Topic identifier to include in the WS URL query param. */
  topicId?: string;
  /** When false, the WebSocket will not auto-connect (and will disconnect if connected). */
  enabled?: boolean;
  /** Called once when the server sends session_start — use to initiate Simli WebRTC */
  onSessionStart?: () => void;
  /** Called with raw PCM bytes for each audio_chunk — use to forward to Simli DataChannel */
  onAudioChunk?: (pcm: Uint8Array) => void;
  /** Called when the backend reports a Simli avatar connection failure */
  onSimliError?: (message: string) => void;
  /** Skip real WebSocket and simulate a fake tutor response (for local UI dev). Default false. */
  _useMock?: boolean;
}

export interface TutorSocket {
  connect(): void;
  disconnect(): void;
  /** Send a binary PCM Int16 chunk from the mic AudioWorklet */
  sendAudioChunk(chunk: ArrayBuffer): void;
  /** Signal that the student has finished speaking (end-of-utterance) */
  sendEndOfUtterance(): void;
  /** Signal the backend to generate the greeting (Turn 0) */
  sendStartLesson(): void;
  sendBargeIn(): void;
  isConnected: boolean;
  /** The underlying WebSocket, for use by Simli signaling */
  readonly ws: WebSocket | null;
}

type ServerMessage =
  | { type: "session_start"; session_id: string; topic?: string; total_turns?: number }
  | { type: "session_restore"; session_id: string; topic?: string; total_turns?: number; turn_count?: number; history?: Array<{ role: string; content: string }> }
  | { type: "tutor_text_chunk"; text: string; timing: Record<string, number | null>; is_greeting?: boolean }
  | { type: "audio_chunk"; data: string }
  | { type: "simli_sdp_answer"; sdp: string; iceServers?: RTCIceServer[] }
  | { type: "barge_in_ack" }
  | { type: "student_transcript"; text: string }
  | { type: "student_partial"; text: string }
  | { type: "session_complete"; turn_number: number; total_turns: number; message: string }
  | { type: "greeting_complete" }
  | { type: "error"; code: string; message?: string; timing?: Record<string, number | null> };

/** localStorage key for persisting the session ID across page refreshes. */
const SESSION_ID_KEY = "tutorSessionId";

/**
 * Manages a WebSocket connection to the tutor-server.
 *
 * Binary messages: PCM Int16 audio frames sent from the mic AudioWorklet.
 * JSON messages: control signals (end_of_utterance, barge_in) and server events.
 *
 * TTS audio_chunk messages are decoded via AudioContext and queued for
 * sequential playback so chunks play in order without gaps.
 */
export function useTutorSocket(opts: TutorSocketOptions): TutorSocket {
  const wsRef = useRef<WebSocket | null>(null);
  const connectedRef = useRef(false);
  const turnStartRef = useRef<number>(0);
  const reconnectTimerRef = useRef<number | null>(null);
  const reconnectAttemptRef = useRef(0);
  const manualDisconnectRef = useRef(false);

  // ── Stabilize opts via ref so callbacks don't depend on object identity ──
  // Without this, handleMessage/connect are recreated every render because
  // opts.store is a new object each time, causing the WS useEffect to
  // disconnect + reconnect on every state change — silently dropping audio.
  const optsRef = useRef(opts);
  optsRef.current = opts;

  // Build WS URL with topic and session_id query parameters
  const buildServerUrl = useCallback(() => {
    const params = new URLSearchParams();
    if (opts.topicId) params.set("topic", opts.topicId);
    const savedSessionId = localStorage.getItem(SESSION_ID_KEY);
    if (savedSessionId) params.set("session_id", savedSessionId);
    const qs = params.toString() ? `?${params.toString()}` : "";
    return opts.serverUrl ??
      `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}/session${qs}`;
  }, [opts.serverUrl, opts.topicId]);

  // Store the URL in a ref so `connect` doesn't depend on the string value.
  // Without this, connect's identity changes when session_id enters localStorage
  // (after session_start), triggering the main effect to disconnect + reconnect,
  // which destroys the working Simli PeerConnection.
  const serverUrlRef = useRef('');
  serverUrlRef.current = buildServerUrl();

  // Audio playback — play each chunk immediately as it arrives (no buffering)
  const audioCtxRef = useRef<AudioContext | null>(null);
  const playbackQueueRef = useRef<Promise<void>>(Promise.resolve());
  // Track time-to-first-audio on the frontend (mic release → first audio byte played)
  const firstAudioPlayedRef = useRef<boolean>(false);

  function getAudioContext(): AudioContext {
    if (!audioCtxRef.current || audioCtxRef.current.state === "closed") {
      audioCtxRef.current = new AudioContext({ sampleRate: 16000 });
    }
    return audioCtxRef.current;
  }

  /** Play a single PCM/WAV chunk immediately via the sequential playback queue. */
  function playChunkNow(bytes: Uint8Array): void {
    if (bytes.length === 0) return;

    const ctx = getAudioContext();

    // Check if this is a WAV file (has RIFF header)
    const isWav = bytes.length > 44 &&
      bytes[0] === 0x52 && bytes[1] === 0x49 &&
      bytes[2] === 0x46 && bytes[3] === 0x46; // "RIFF"

    // Track frontend time-to-first-audio
    const isFirst = !firstAudioPlayedRef.current;
    if (isFirst) firstAudioPlayedRef.current = true;

    playbackQueueRef.current = playbackQueueRef.current.then(async () => {
      try {
        let audioBuffer: AudioBuffer;

        if (isWav) {
          audioBuffer = await ctx.decodeAudioData((bytes.buffer as ArrayBuffer).slice(0));
        } else {
          // Raw PCM Int16 LE → Float32
          const int16 = new Int16Array(bytes.buffer, 0, Math.floor(bytes.length / 2));
          audioBuffer = ctx.createBuffer(1, int16.length, 16000);
          const channel = audioBuffer.getChannelData(0);
          for (let i = 0; i < int16.length; i++) {
            channel[i] = int16[i] / 32768;
          }
        }

        // Record frontend e2e: mic release → first audio byte actually starts playing
        if (isFirst && turnStartRef.current > 0) {
          const frontendE2eMs = Date.now() - turnStartRef.current;
          console.log(ts(), `[TutorSocket] frontend_e2e_ms=${frontendE2eMs} (mic release → first audio played)`);
          optsRef.current.store.setLatency(frontendE2eMs);
        }

        await new Promise<void>((resolve) => {
          const source = ctx.createBufferSource();
          source.buffer = audioBuffer;
          source.connect(ctx.destination);
          source.onended = () => resolve();
          source.start();
        });
      } catch (err) {
        console.warn(ts(), "[TutorSocket] Audio playback error:", err);
      }
    });
  }

  /** Decode a base64-encoded audio chunk and play it immediately. */
  function playAudioChunk(base64Data: string): void {
    const binary = atob(base64Data);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    playChunkNow(bytes);
  }

  function clearReconnectTimer(): void {
    if (reconnectTimerRef.current !== null) {
      window.clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
  }

  const handleMessage = useCallback(
    (raw: MessageEvent<string>) => {
      // Read from ref so this callback is stable (no deps on opts object identity)
      const { store, onSessionStart, onAudioChunk } = optsRef.current;

      let msg: ServerMessage;
      try {
        msg = JSON.parse(raw.data) as ServerMessage;
      } catch {
        return;
      }

      if (msg.type === "session_start") {
        console.debug(ts(), "[TutorSocket] session_start received, session_id:", msg.session_id, "topic:", msg.topic);
        // Persist session ID for reconnection on page refresh
        localStorage.setItem(SESSION_ID_KEY, msg.session_id);
        store.setMode("idle");
        // Set initial turn info from server if provided
        if (msg.total_turns) {
          store.setTurnInfo(0, msg.total_turns);
        }
        onSessionStart?.();
      } else if (msg.type === "session_restore") {
        console.debug(ts(), "[TutorSocket] session_restore received, session_id:", msg.session_id, "turn_count:", msg.turn_count);
        // Persist session ID (may be the same, but ensures consistency)
        localStorage.setItem(SESSION_ID_KEY, msg.session_id);
        // Convert backend history [{role, content}] to ConversationEntry[]
        const restoredHistory = (msg.history ?? []).map((entry, idx) => ({
          id: `restored-${idx}-${Date.now()}`,
          role: (entry.role === "user" ? "student" : "tutor") as "student" | "tutor",
          text: entry.content,
          timestamp: Date.now() - (msg.history!.length - idx) * 1000, // approximate timestamps
        }));
        store.restoreSession(
          restoredHistory,
          msg.turn_count ?? 0,
          msg.total_turns ?? 15,
        );
        onSessionStart?.();
      } else if (msg.type === "tutor_text_chunk") {
        // Extract per-stage timing if present.
        // Use TTF (time-to-first) metrics for STT/LLM/TTS — these reflect
        // perceived responsiveness, not total processing time.
        if (msg.timing) {
          const entry = {
            stt_ms: (msg.timing["stt_finish_ms"] as number | null) ?? null,
            llm_ms: (msg.timing["llm_ttf_ms"] as number | null) ?? (msg.timing["llm_duration_ms"] as number | null) ?? null,
            tts_ms: (msg.timing["tts_ttf_ms"] as number | null) ?? (msg.timing["tts_duration_ms"] as number | null) ?? null,
            total_ms: (msg.timing["turn_duration_ms"] as number | null) ?? null,
          };
          store.setStageLatency(entry);

          // Use backend-provided turn number (source of truth)
          const turnNum = (msg.timing["turn_number"] as number | null) ?? store.turnNumber;
          const totalTurns = (msg.timing["total_turns"] as number | null) ?? store.totalTurns;
          store.setTurnInfo(turnNum, totalTurns);

          // Don't push greeting latency into the turn history chart
          if (!msg.is_greeting) {
            store.pushLatencyHistory({
              turn: turnNum,
              ...entry,
            });
          }
        }
        // Audio is already playing (streamed on each audio_chunk).
        // Show the full text immediately and commit the response.
        if (msg.is_greeting) {
          console.debug(ts(), "[TutorSocket] tutor_text_chunk (greeting):", msg.text.substring(0, 60) + "...");
          store.startGreeting();
        } else {
          console.debug(ts(), "[TutorSocket] tutor_text_chunk (turn):", msg.text.substring(0, 60) + "...");
          store.startTutorResponse();
        }
        const words = msg.text.split(" ");
        // Show all words at once — audio is already playing, no need
        // for artificial 80ms staggering that inflates perceived latency.
        for (const word of words) {
          store.appendStreamWord(word);
        }
        // Reset turn timer (frontend e2e was already recorded on first audio_chunk)
        turnStartRef.current = 0;
        setTimeout(() => store.commitTutorResponse(), 400);
      } else if (msg.type === "audio_chunk") {
        // Play immediately — don't buffer until tutor_text_chunk
        console.debug(ts(), "[TutorSocket] audio_chunk received, base64 len:", msg.data.length);
        playAudioChunk(msg.data);
        // Forward raw PCM to Simli DataChannel for avatar lip-sync
        if (onAudioChunk) {
          const binary = atob(msg.data);
          const bytes = new Uint8Array(binary.length);
          for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
          onAudioChunk(bytes);
        }
      } else if (msg.type === "simli_sdp_answer") {
        console.debug(ts(), "[TutorSocket] simli_sdp_answer received, sdp len:", msg.sdp?.length, "iceServers:", msg.iceServers?.length ?? 0);
        // Dispatch custom event so useSimliWebRTC can pick it up
        window.dispatchEvent(new CustomEvent("simli:sdp-answer", {
          detail: { sdp: msg.sdp, iceServers: msg.iceServers },
        }));
      } else if (msg.type === "student_transcript") {
        store.updateLastStudentUtterance(msg.text);
      } else if (msg.type === "student_partial") {
        // Live streaming partial transcript — update the placeholder in real time
        store.updateLastStudentUtterance(msg.text);
      } else if (msg.type === "session_complete") {
        store.setTurnInfo(msg.turn_number, msg.total_turns);
        store.setSessionComplete(true);
        // Clear persisted session — lesson is done, no reconnection needed
        localStorage.removeItem(SESSION_ID_KEY);
        console.log(ts(), "[TutorSocket] Session complete:", msg.message);
      } else if (msg.type === "greeting_complete") {
        // Greeting audio is done — ensure mode returns to idle so mic enables
        store.setMode("idle");
        console.log(ts(), "[TutorSocket] Greeting complete — mic enabled");
      } else if (msg.type === "barge_in_ack") {
        // Cancel any queued audio playback by replacing the queue
        playbackQueueRef.current = Promise.resolve();
        store.bargeIn();
      } else if (msg.type === "error") {
        // Simli-specific errors — surface via dedicated callback so the
        // avatar UI can show an error state with a retry button.
        const isSimliError = msg.code === "SIMLI_CONNECT_FAILED" || msg.code === "SIMLI_NOT_CONFIGURED";
        if (isSimliError) {
          const errorMsg = msg.code === "SIMLI_NOT_CONFIGURED"
            ? "Avatar not configured. Check SIMLI_API_KEY and SIMLI_FACE_ID."
            : "Avatar connection failed. You can retry or continue without video.";
          optsRef.current.onSimliError?.(errorMsg);
        }

        if (msg.timing) {
          const entry = {
            stt_ms: (msg.timing["stt_finish_ms"] as number | null) ?? null,
            llm_ms: (msg.timing["llm_ttf_ms"] as number | null) ?? (msg.timing["llm_duration_ms"] as number | null) ?? null,
            tts_ms: (msg.timing["tts_ttf_ms"] as number | null) ?? (msg.timing["tts_duration_ms"] as number | null) ?? null,
            total_ms: (msg.timing["turn_duration_ms"] as number | null) ?? null,
          };
          store.setStageLatency(entry);
          // Update turn info from error timing if available
          const turnNum = (msg.timing["turn_number"] as number | null) ?? null;
          const totalTurns = (msg.timing["total_turns"] as number | null) ?? null;
          if (turnNum !== null && totalTurns !== null) {
            store.setTurnInfo(turnNum, totalTurns);
          }
          store.pushLatencyHistory({
            turn: turnNum ?? store.turnNumber,
            ...entry,
          });
        }
        console.error(ts(), "[TutorSocket] Server error:", msg.code, msg.message);
        // Simli errors don't affect session mode — the student can still
        // talk to the tutor; only the avatar video is unavailable.
        if (isSimliError) {
          // Don't change mode — student can still use the tutor without avatar
        } else if (msg.code === "GREETING_FAILED") {
          // Greeting failed — surface error and reset mode so UI isn't stuck.
          // The backend does NOT send greeting_complete on failure, so we
          // must reset mode here ourselves.
          store.setError(msg.message ?? "Greeting failed. Please go back and try again.");
          store.setMode("idle");
        } else {
          store.setMode("idle");
        }
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    []
  );

  const connect = useCallback(() => {
    manualDisconnectRef.current = false;
    if (optsRef.current._useMock) {
      // Mock mode: immediately mark as connected and fire a fake session_start,
      // then simulate a tutor response whenever sendEndOfUtterance is called.
      clearReconnectTimer();
      reconnectAttemptRef.current = 0;
      connectedRef.current = true;
      setTimeout(() => optsRef.current.onSessionStart?.(), 100);
      return;
    }

    if (wsRef.current && connectedRef.current) return;

    const ws = new WebSocket(serverUrlRef.current);
    wsRef.current = ws;
    ws.binaryType = "arraybuffer";

    ws.onopen = () => {
      // Guard: only update state if this WS is still the current one.
      // Prevents a stale WS (from React StrictMode double-invoke or HMR)
      // from clobbering a newer connection's state.
      if (wsRef.current !== ws) return;
      connectedRef.current = true;
      clearReconnectTimer();
      reconnectAttemptRef.current = 0;
      optsRef.current.store.setError(null);
      (window as unknown as Record<string, unknown>).__tutorWs = ws;
      console.log(ts(), "[TutorSocket] WS open, exposed as window.__tutorWs");
    };

    ws.onmessage = handleMessage;

    ws.onclose = () => {
      // Guard: only clear refs if this WS is still the current one.
      // Without this, a stale WS closing asynchronously (after disconnect()
      // already created a replacement) would null out wsRef and break
      // Simli signaling with "WebSocket not open — cannot connect".
      if (wsRef.current !== ws) return;
      connectedRef.current = false;
      wsRef.current = null;
      if (manualDisconnectRef.current || optsRef.current.enabled === false || optsRef.current._useMock) {
        return;
      }
      if (reconnectTimerRef.current !== null) {
        return;
      }
      const attempt = reconnectAttemptRef.current + 1;
      reconnectAttemptRef.current = attempt;
      const delayMs = Math.min(2000, 250 * 2 ** (attempt - 1));
      optsRef.current.store.setError("Connection lost. Reconnecting...");
      reconnectTimerRef.current = window.setTimeout(() => {
        reconnectTimerRef.current = null;
        if (manualDisconnectRef.current || wsRef.current) {
          return;
        }
        connect();
      }, delayMs);
    };

    ws.onerror = () => {
      if (wsRef.current !== ws) return;
      connectedRef.current = false;
    };
  }, [handleMessage]);

  const disconnect = useCallback(() => {
    manualDisconnectRef.current = true;
    clearReconnectTimer();
    const ws = wsRef.current;
    if (ws) {
      if (ws.readyState === WebSocket.CONNECTING) {
        // Closing a CONNECTING socket triggers a browser warning. Defer the
        // close until the socket opens so it closes cleanly. This is the
        // common path in React StrictMode's double-invoke of effects.
        ws.onopen = () => ws.close();
        // Null ALL handlers so the brief open→close cycle is completely
        // silent: no state updates, no onSessionStart, no Simli handshake.
        ws.onmessage = null;
        ws.onclose = null;
        ws.onerror = null;
      } else {
        ws.close();
      }
    }
    wsRef.current = null;
    connectedRef.current = false;
    try { audioCtxRef.current?.close(); } catch { /* may already be closed */ }
    audioCtxRef.current = null;
  }, []);

  const sendAudioChunk = useCallback((chunk: ArrayBuffer) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      optsRef.current.store.setError("Connection unavailable. Reconnecting...");
      return;
    }
    wsRef.current.send(chunk);
  }, []);

  const sendEndOfUtterance = useCallback(() => {
    if (optsRef.current._useMock) {
      turnStartRef.current = Date.now();
      const fakeResponses = [
        "That's a great question! Photosynthesis is how plants make their own food using sunlight.",
        "What do you think the plant needs besides sunlight to carry out photosynthesis?",
        "Exactly! And where does the plant store the energy it produces?",
      ];
      const text = fakeResponses[Math.floor(Math.random() * fakeResponses.length)];
      setTimeout(() => {
        const { store } = optsRef.current;
        store.startTutorResponse();
        const words = text.split(" ");
        words.forEach((word, i) => {
          setTimeout(() => {
            store.appendStreamWord(word);
            if (i === words.length - 1) {
              store.setLatency(Date.now() - turnStartRef.current);
              turnStartRef.current = 0;
              // Simulate backend turn info
              store.setTurnInfo(store.turnNumber + 1, store.totalTurns);
              setTimeout(() => store.commitTutorResponse(), 400);
            }
          }, i * 80);
        });
      }, 1500);
      return;
    }
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      optsRef.current.store.setError("Connection unavailable. Reconnecting...");
      return;
    }
    turnStartRef.current = Date.now();
    firstAudioPlayedRef.current = false;  // Reset for new turn
    wsRef.current.send(JSON.stringify({ type: "end_of_utterance" }));
  }, []);

  const sendStartLesson = useCallback(() => {
    if (optsRef.current._useMock) {
      // Mock greeting: simulate a short delay then a greeting response
      setTimeout(() => {
        const { store } = optsRef.current;
        store.startGreeting();
        const greeting = "Hey there! Plants make their own food — no kitchen needed. How do you think they pull that off?";
        const words = greeting.split(" ");
        for (const word of words) {
          store.appendStreamWord(word);
        }
        setTimeout(() => {
          store.commitTutorResponse();
          // After commit, set mode to idle (simulating greeting_complete)
          setTimeout(() => store.setMode("idle"), 100);
        }, 400);
      }, 800);
      return;
    }
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      console.debug(ts(), "[TutorSocket] sendStartLesson: WS not open, skipping");
      return;
    }
    console.debug(ts(), "[TutorSocket] sendStartLesson: sending start_lesson");
    firstAudioPlayedRef.current = false;
    wsRef.current.send(JSON.stringify({ type: "start_lesson" }));
  }, []);

  const sendBargeIn = useCallback(() => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      optsRef.current.store.setError("Connection unavailable. Reconnecting...");
      return;
    }
    wsRef.current.send(JSON.stringify({ type: "barge_in" }));
  }, []);

  // Gate auto-connect on the `enabled` option
  useEffect(() => {
    if (optsRef.current.enabled === false) {
      console.debug(ts(), "[TutorSocket] enabled=false — disconnecting");
      disconnect();
      return;
    }
    console.debug(ts(), "[TutorSocket] enabled=true — connecting to", serverUrlRef.current);
    connect();
    return () => disconnect();
  }, [connect, disconnect, opts.enabled]);

  return {
    connect,
    disconnect,
    sendAudioChunk,
    sendEndOfUtterance,
    sendStartLesson,
    sendBargeIn,
    get isConnected() {
      return connectedRef.current;
    },
    get ws() {
      return wsRef.current;
    },
  };
}
