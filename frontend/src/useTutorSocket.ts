import { useRef, useCallback, useEffect, useState } from "react";
import type { SessionStore, AvatarProvider, LessonVisualState, SimliMode } from "./types";

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
  /** Called when the server sends session_start or session_restore. */
  onSessionStart?: (kind: "start" | "restore") => void;
  /** Called with the avatar provider from session_start/session_restore */
  onAvatarProvider?: (provider: AvatarProvider) => void;
  /** Called with the active Simli connection mode from session_start/session_restore */
  onSimliMode?: (mode: SimliMode) => void;
  /** Called with raw PCM bytes for each audio_chunk — use to forward to Simli DataChannel */
  onAudioChunk?: (pcm: Uint8Array) => void;
  /** Return false to suppress browser AudioContext playback for a given mode/provider. */
  shouldPlayAudioChunk?: () => boolean;
  /** Called after the backend has finished streaming audio for the current tutor response. */
  onAudioStreamComplete?: () => void;
  /** Called when the backend reports a Simli avatar connection failure */
  onSimliError?: (message: string) => void;
  /** Called when the backend sends spatialreal_session_init with token and config */
  onSpatialRealInit?: (sessionToken: string, appId: string, avatarId: string) => void;
  /** Called when the backend sends simli_sdk_init with token and ICE config */
  onSimliSdkInit?: (sessionToken: string, iceServers: RTCIceServer[] | null) => void;
  /** Called with the wall-clock timestamp (Date.now()) when the first audio byte of a turn
   *  starts playing in the browser. Used by App.tsx to compute lip-sync offset. */
  onFirstAudioPlayed?: (tsMs: number) => void;
  /** Skip real WebSocket and simulate a fake tutor response (for local UI dev). Default false. */
  _useMock?: boolean;
}

export interface TutorSocket {
  connect(): void;
  disconnect(): void;
  reconnect(opts?: { freshSession?: boolean }): void;
  /** Send a binary PCM Int16 chunk from the mic AudioWorklet */
  sendAudioChunk(chunk: ArrayBuffer): void;
  /** Signal that the student has finished speaking (end-of-utterance) */
  sendEndOfUtterance(): void;
  /** Signal the backend to generate the greeting (Turn 0) */
  sendStartLesson(): void;
  /** Signal the backend to resume a restored session (welcome-back prompt) */
  sendContinueLesson(): void;
  sendBargeIn(): void;
  isConnected: boolean;
  sessionKind: "start" | "restore" | null;
  /** The underlying WebSocket, for use by Simli signaling */
  readonly ws: WebSocket | null;
}

type ServerMessage =
  | { type: "session_start"; session_id: string; topic?: string; total_turns?: number; avatar_provider?: AvatarProvider; simli_mode?: SimliMode }
  | { type: "session_restore"; session_id: string; topic?: string; total_turns?: number; turn_count?: number; avatar_provider?: AvatarProvider; simli_mode?: SimliMode; history?: Array<{ role: string; content: string }> }
  | { type: "spatialreal_session_init"; session_token: string; app_id: string; avatar_id: string }
  | { type: "simli_sdk_init"; session_token: string; ice_servers?: RTCIceServer[] }
  | { type: "tutor_text_chunk"; text: string; timing: Record<string, number | null>; is_greeting?: boolean }
  | { type: "audio_chunk"; data: string }
  | { type: "simli_sdp_answer"; sdp: string; iceServers?: RTCIceServer[] }
  | { type: "barge_in_ack" }
  | { type: "student_transcript"; text: string }
  | { type: "student_partial"; text: string }
  | { type: "session_complete"; turn_number: number; total_turns: number; message: string }
  | { type: "greeting_complete" }
  | { type: "error"; code: string; message?: string; timing?: Record<string, number | null> }
  | {
      type: "lesson_visual_update";
      diagram_id: string;
      step_id: number;
      step_label: string;
      total_steps: number;
      highlight_keys?: string[];
      unlocked_elements?: string[];
      progress_completed?: number;
      progress_total?: number;
      progress_label?: string;
      caption?: string;
      emoji_diagram: string;
      turn_number: number;
      is_recap: boolean;
    };

/** localStorage key for persisting the session ID across page refreshes. */
export const SESSION_ID_KEY = "tutorSessionId";
export const SESSION_TOPIC_KEY = "tutorSessionTopicId";
export const SESSION_AVATAR_KEY = "tutorSessionAvatar";
export const SESSION_SIMLI_MODE_KEY = "tutorSessionSimliMode";

function getRequestedAvatarProvider(): AvatarProvider {
  const avatarParam = new URLSearchParams(window.location.search).get("avatar");
  return avatarParam === "spatialreal" ? "spatialreal" : "simli";
}

function getRequestedSimliMode(): SimliMode {
  const modeParam = new URLSearchParams(window.location.search).get("simli_mode");
  return modeParam === "sdk" ? "sdk" : "custom";
}

function getSessionIdFromUrl(): string | null {
  return new URLSearchParams(window.location.search).get("session_id");
}

function syncSessionIdInUrl(sessionId: string | null): void {
  const url = new URL(window.location.href);
  if (sessionId) {
    url.searchParams.set("session_id", sessionId);
  } else {
    url.searchParams.delete("session_id");
  }
  window.history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);
}

function clearPersistedSession(): void {
  localStorage.removeItem(SESSION_ID_KEY);
  localStorage.removeItem(SESSION_TOPIC_KEY);
  localStorage.removeItem(SESSION_AVATAR_KEY);
  localStorage.removeItem(SESSION_SIMLI_MODE_KEY);
  syncSessionIdInUrl(null);
}

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
  const [isConnectedState, setIsConnectedState] = useState(false);
  const [sessionKind, setSessionKind] = useState<"start" | "restore" | null>(null);
  const turnStartRef = useRef<number>(0);
  const reconnectTimerRef = useRef<number | null>(null);
  const reconnectAttemptRef = useRef(0);
  const manualDisconnectRef = useRef(false);
  const freshSessionRef = useRef(false);
  const responseCommitTimerRef = useRef<number | null>(null);
  const awaitingCommitTurnRef = useRef<number | null>(null);
  const committedTurnRef = useRef(0);
  const pendingVisualRef = useRef<LessonVisualState | null>(null);
  const pendingCompletionRef = useRef<Extract<ServerMessage, { type: "session_complete" }> | null>(null);
  const appliedVisualRef = useRef<{ turnNumber: number; isRecap: boolean }>({
    turnNumber: -1,
    isRecap: false,
  });

  // ── Stabilize opts via ref so callbacks don't depend on object identity ──
  // Without this, handleMessage/connect are recreated every render because
  // opts.store is a new object each time, causing the WS useEffect to
  // disconnect + reconnect on every state change — silently dropping audio.
  const optsRef = useRef(opts);
  optsRef.current = opts;

  // Build WS URL with topic, session_id, and avatar query parameters
  const buildServerUrl = useCallback(() => {
    const params = new URLSearchParams();
    if (opts.topicId) params.set("topic", opts.topicId);
    const urlSessionId = getSessionIdFromUrl();
    const savedAvatar = localStorage.getItem(SESSION_AVATAR_KEY);
    const savedSimliMode = localStorage.getItem(SESSION_SIMLI_MODE_KEY);
    const requestedAvatar = getRequestedAvatarProvider();
    const requestedSimliMode = getRequestedSimliMode();
    if (
      !freshSessionRef.current &&
      urlSessionId &&
      (savedAvatar === null || savedAvatar === requestedAvatar) &&
      (savedSimliMode === null || savedSimliMode === requestedSimliMode)
    ) {
      params.set("session_id", urlSessionId);
    }
    if (requestedAvatar) params.set("avatar", requestedAvatar);
    if (requestedAvatar === "simli") params.set("simli_mode", requestedSimliMode);
    const qs = params.toString() ? `?${params.toString()}` : "";
    if (opts.serverUrl) {
      if (!qs) return opts.serverUrl;
      const separator = opts.serverUrl.includes("?") ? "&" : "?";
      return `${opts.serverUrl}${separator}${params.toString()}`;
    }
    return `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}/session${qs}`;
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
  // Generation counter: incremented on disconnect to cancel queued audio chunks.
  const audioGenRef = useRef(0);
  // Track time-to-first-audio on the frontend (mic release → first audio byte played)
  const firstAudioPlayedRef = useRef<boolean>(false);
  // Stores the most recent frontend_e2e_ms so it can be included in the StageLatency entry
  // when tutor_text_chunk timing arrives (which is after audio chunks).
  const e2eMsRef = useRef<number | null>(null);

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

    const gen = audioGenRef.current;
    playbackQueueRef.current = playbackQueueRef.current.then(async () => {
      // Stale audio from a previous connection — skip silently.
      if (audioGenRef.current !== gen) return;
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
          const nowMs = Date.now();
          const frontendE2eMs = nowMs - turnStartRef.current;
          console.log(ts(), `[TutorSocket] frontend_e2e_ms=${frontendE2eMs} (mic release → first audio played)`);
          e2eMsRef.current = frontendE2eMs;
          optsRef.current.store.setLatency(frontendE2eMs);
          optsRef.current.onFirstAudioPlayed?.(nowMs);
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

  function decodeAudioChunk(base64Data: string): Uint8Array {
    const binary = atob(base64Data);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    return bytes;
  }

  function clearReconnectTimer(): void {
    if (reconnectTimerRef.current !== null) {
      window.clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
  }

  function clearResponseCommitTimer(): void {
    if (responseCommitTimerRef.current !== null) {
      window.clearTimeout(responseCommitTimerRef.current);
      responseCommitTimerRef.current = null;
    }
  }

  function resetTurnSync(turnNumber: number): void {
    clearResponseCommitTimer();
    awaitingCommitTurnRef.current = null;
    committedTurnRef.current = turnNumber;
    pendingVisualRef.current = null;
    pendingCompletionRef.current = null;
    appliedVisualRef.current = { turnNumber: -1, isRecap: false };
  }

  function shouldApplyVisual(visual: LessonVisualState): boolean {
    const applied = appliedVisualRef.current;
    if (visual.turnNumber > applied.turnNumber) return true;
    if (visual.turnNumber < applied.turnNumber) return false;
    return visual.isRecap && !applied.isRecap;
  }

  function applyVisual(store: SessionStore, visual: LessonVisualState): void {
    if (!shouldApplyVisual(visual)) return;
    store.setVisual(visual);
    appliedVisualRef.current = {
      turnNumber: visual.turnNumber,
      isRecap: visual.isRecap,
    };
  }

  function flushDeferredTurnState(store: SessionStore): void {
    const committedTurn = committedTurnRef.current;
    const pendingVisual = pendingVisualRef.current;
    if (pendingVisual && pendingVisual.turnNumber <= committedTurn) {
      applyVisual(store, pendingVisual);
      pendingVisualRef.current = null;
    }

    const pendingCompletion = pendingCompletionRef.current;
    if (pendingCompletion && pendingCompletion.turn_number <= committedTurn) {
      store.setTurnInfo(pendingCompletion.turn_number, pendingCompletion.total_turns);
      store.setSessionComplete(true);
      clearPersistedSession();
      console.log(ts(), "[TutorSocket] Session complete:", pendingCompletion.message);
      pendingCompletionRef.current = null;
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
        console.debug(ts(), "[TutorSocket] session_start received, session_id:", msg.session_id, "topic:", msg.topic, "avatar_provider:", msg.avatar_provider);
        const persistedAvatar = msg.avatar_provider ?? getRequestedAvatarProvider();
        const persistedSimliMode = msg.simli_mode ?? getRequestedSimliMode();
        freshSessionRef.current = false;
        resetTurnSync(0);
        setSessionKind("start");
        localStorage.setItem(SESSION_ID_KEY, msg.session_id);
        if (msg.topic) localStorage.setItem(SESSION_TOPIC_KEY, msg.topic);
        localStorage.setItem(SESSION_AVATAR_KEY, persistedAvatar);
        localStorage.setItem(SESSION_SIMLI_MODE_KEY, persistedSimliMode);
        syncSessionIdInUrl(msg.session_id);
        store.setMode("idle");
        // Set initial turn info from server if provided
        if (msg.total_turns) {
          store.setTurnInfo(0, msg.total_turns);
        }
        // Notify App which avatar provider is active
        if (msg.avatar_provider) {
          optsRef.current.onAvatarProvider?.(msg.avatar_provider);
        }
        if (msg.simli_mode) {
          optsRef.current.onSimliMode?.(msg.simli_mode);
        }
        onSessionStart?.("start");
      } else if (msg.type === "session_restore") {
        console.debug(ts(), "[TutorSocket] session_restore received, session_id:", msg.session_id, "turn_count:", msg.turn_count, "avatar_provider:", msg.avatar_provider);
        const persistedAvatar = localStorage.getItem(SESSION_AVATAR_KEY) ?? msg.avatar_provider ?? getRequestedAvatarProvider();
        const persistedSimliMode = localStorage.getItem(SESSION_SIMLI_MODE_KEY) ?? msg.simli_mode ?? getRequestedSimliMode();
        freshSessionRef.current = false;
        resetTurnSync(msg.turn_count ?? 0);
        setSessionKind("restore");
        localStorage.setItem(SESSION_ID_KEY, msg.session_id);
        if (msg.topic) localStorage.setItem(SESSION_TOPIC_KEY, msg.topic);
        localStorage.setItem(SESSION_AVATAR_KEY, persistedAvatar);
        localStorage.setItem(SESSION_SIMLI_MODE_KEY, persistedSimliMode);
        syncSessionIdInUrl(msg.session_id);
        // Notify App which avatar provider is active
        if (msg.avatar_provider) {
          optsRef.current.onAvatarProvider?.(msg.avatar_provider);
        }
        if (msg.simli_mode) {
          optsRef.current.onSimliMode?.(msg.simli_mode);
        }
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
        onSessionStart?.("restore");
      } else if (msg.type === "tutor_text_chunk") {
        const turnNum =
          (msg.timing?.["turn_number"] as number | null) ??
          committedTurnRef.current;
        const totalTurns =
          (msg.timing?.["total_turns"] as number | null) ??
          store.totalTurns;
        awaitingCommitTurnRef.current = turnNum;

        // Extract per-stage timing if present.
        // Use TTF (time-to-first) metrics for STT/LLM/TTS — these reflect
        // perceived responsiveness, not total processing time.
        if (msg.timing) {
          const entry = {
            stt_ms: (msg.timing["stt_finish_ms"] as number | null) ?? null,
            llm_ms: (msg.timing["llm_ttf_ms"] as number | null) ?? (msg.timing["llm_duration_ms"] as number | null) ?? null,
            tts_ms: (msg.timing["tts_ttf_ms"] as number | null) ?? (msg.timing["tts_duration_ms"] as number | null) ?? null,
            total_ms: (msg.timing["turn_duration_ms"] as number | null) ?? null,
            // Frontend-measured fields — e2e was recorded when first audio_chunk played.
            e2e_ms: e2eMsRef.current,
            response_complete_ms: null as number | null,
            lip_sync_ms: null as number | null,
          };
          store.setStageLatency(entry);

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

        // Capture turn start BEFORE zeroing so response_complete_ms can be measured
        // as elapsed time from mic release to last audio chunk finishing.
        const responseTurnStart = turnStartRef.current;
        // Reset turn timer (frontend e2e was already recorded on first audio_chunk)
        turnStartRef.current = 0;

        // Chain onto playback queue: fires after the LAST audio chunk finishes playing.
        if (responseTurnStart > 0) {
          const capturedGen = audioGenRef.current;
          const isGreetingTurn = msg.is_greeting ?? false;
          playbackQueueRef.current = playbackQueueRef.current.then(() => {
            // Skip if a barge-in reset the generation (stale turn).
            if (audioGenRef.current !== capturedGen) return;
            const responseCompleteMs = Date.now() - responseTurnStart;
            console.log(ts(), `[TutorSocket] response_complete_ms=${responseCompleteMs} (mic release → last audio chunk)`);
            optsRef.current.store.setResponseComplete(responseCompleteMs);
            if (!isGreetingTurn) {
              optsRef.current.store.updateLastLatencyHistory({ response_complete_ms: responseCompleteMs });
            }
          });
        }

        clearResponseCommitTimer();
        responseCommitTimerRef.current = window.setTimeout(() => {
          store.setTurnInfo(turnNum, totalTurns);
          store.commitTutorResponse();
          committedTurnRef.current = Math.max(committedTurnRef.current, turnNum);
          awaitingCommitTurnRef.current = null;
          responseCommitTimerRef.current = null;
          flushDeferredTurnState(store);
        }, 400);
        optsRef.current.onAudioStreamComplete?.();
      } else if (msg.type === "audio_chunk") {
        // Play immediately — don't buffer until tutor_text_chunk
        console.debug(ts(), "[TutorSocket] audio_chunk received, base64 len:", msg.data.length);
        const bytes = decodeAudioChunk(msg.data);
        if (optsRef.current.shouldPlayAudioChunk?.() ?? true) {
          playChunkNow(bytes);
        }
        // Forward raw PCM to Simli DataChannel for avatar lip-sync
        if (onAudioChunk) {
          onAudioChunk(bytes);
        }
      } else if (msg.type === "simli_sdp_answer") {
        console.debug(ts(), "[TutorSocket] simli_sdp_answer received, sdp len:", msg.sdp?.length, "iceServers:", msg.iceServers?.length ?? 0);
        // Dispatch custom event so useSimliWebRTC can pick it up
        window.dispatchEvent(new CustomEvent("simli:sdp-answer", {
          detail: { sdp: msg.sdp, iceServers: msg.iceServers },
        }));
      } else if (msg.type === "spatialreal_session_init") {
        console.debug(ts(), "[TutorSocket] spatialreal_session_init received, app_id:", msg.app_id, "avatar_id:", msg.avatar_id);
        optsRef.current.onSpatialRealInit?.(msg.session_token, msg.app_id, msg.avatar_id);
      } else if (msg.type === "simli_sdk_init") {
        console.debug(ts(), "[TutorSocket] simli_sdk_init received, ice_servers:", msg.ice_servers?.length ?? 0);
        optsRef.current.onSimliSdkInit?.(msg.session_token, msg.ice_servers ?? null);
      } else if (msg.type === "student_transcript") {
        store.updateLastStudentUtterance(msg.text);
      } else if (msg.type === "student_partial") {
        // Live streaming partial transcript — update the placeholder in real time
        store.updateLastStudentUtterance(msg.text);
      } else if (msg.type === "session_complete") {
        if (
          awaitingCommitTurnRef.current !== null &&
          msg.turn_number >= awaitingCommitTurnRef.current
        ) {
          pendingCompletionRef.current = msg;
        } else {
          store.setTurnInfo(msg.turn_number, msg.total_turns);
          store.setSessionComplete(true);
          clearPersistedSession();
          console.log(ts(), "[TutorSocket] Session complete:", msg.message);
        }
      } else if (msg.type === "greeting_complete") {
        // Greeting audio is done — ensure mode returns to idle so mic enables
        store.setMode("idle");
        console.log(ts(), "[TutorSocket] Greeting complete — mic enabled");
      } else if (msg.type === "barge_in_ack") {
        // Cancel any queued audio playback by replacing the queue
        playbackQueueRef.current = Promise.resolve();
        clearResponseCommitTimer();
        awaitingCommitTurnRef.current = null;
        pendingVisualRef.current = null;
        e2eMsRef.current = null;
        pendingCompletionRef.current = null;
        store.bargeIn();
      } else if (msg.type === "error") {
        // Avatar-specific errors — surface via dedicated callback so the
        // avatar UI can show an error state with a retry button.
        const isSimliError = msg.code === "SIMLI_CONNECT_FAILED" || msg.code === "SIMLI_NOT_CONFIGURED";
        const isSpatialRealError = msg.code === "SPATIALREAL_INIT_FAILED";
        if (isSimliError) {
          const errorMsg = msg.code === "SIMLI_NOT_CONFIGURED"
            ? "Avatar not configured. Check SIMLI_API_KEY and SIMLI_FACE_ID."
            : "Avatar connection failed. You can retry or continue without video.";
          optsRef.current.onSimliError?.(errorMsg);
        }
        if (isSpatialRealError) {
          optsRef.current.onSimliError?.(msg.message ?? "SpatialReal avatar initialization failed.");
        }

        if (msg.timing) {
          const entry = {
            stt_ms: (msg.timing["stt_finish_ms"] as number | null) ?? null,
            llm_ms: (msg.timing["llm_ttf_ms"] as number | null) ?? (msg.timing["llm_duration_ms"] as number | null) ?? null,
            tts_ms: (msg.timing["tts_ttf_ms"] as number | null) ?? (msg.timing["tts_duration_ms"] as number | null) ?? null,
            total_ms: (msg.timing["turn_duration_ms"] as number | null) ?? null,
            e2e_ms: e2eMsRef.current,
            response_complete_ms: null as number | null,
            lip_sync_ms: null as number | null,
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
        // Avatar errors don't affect session mode — the student can still
        // talk to the tutor; only the avatar video is unavailable.
        if (isSimliError || isSpatialRealError) {
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
      } else if (msg.type === "lesson_visual_update") {
        const visualState = {
          diagramId: msg.diagram_id,
          stepId: msg.step_id,
          stepLabel: msg.step_label,
          totalSteps: msg.total_steps,
          highlightKeys: msg.highlight_keys ?? [],
          ...(msg.unlocked_elements !== undefined
            ? { unlockedElements: msg.unlocked_elements }
            : {}),
          ...(msg.progress_completed !== undefined
            ? { progressCompleted: msg.progress_completed }
            : {}),
          ...(msg.progress_total !== undefined
            ? { progressTotal: msg.progress_total }
            : {}),
          ...(msg.progress_label !== undefined
            ? { progressLabel: msg.progress_label }
            : {}),
          caption: msg.caption ?? null,
          emojiDiagram: msg.emoji_diagram,
          turnNumber: msg.turn_number,
          isRecap: msg.is_recap,
        } satisfies LessonVisualState;
        const waitingForSameTurnCommit =
          awaitingCommitTurnRef.current !== null &&
          visualState.turnNumber >= awaitingCommitTurnRef.current;
        if (waitingForSameTurnCommit || visualState.turnNumber > committedTurnRef.current) {
          pendingVisualRef.current = visualState;
        } else {
          applyVisual(store, visualState);
        }
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    []
  );

  const connect = useCallback(() => {
    manualDisconnectRef.current = false;
    if (optsRef.current._useMock) {
      clearReconnectTimer();
      reconnectAttemptRef.current = 0;
      connectedRef.current = true;
      setIsConnectedState(true);
      // Trigger a store update so React re-renders and reads isConnected=true
      setTimeout(() => {
        optsRef.current.store.setMode("idle");
        optsRef.current.onSessionStart?.("start");
        // No real avatar in mock mode — signal error so fallback appears immediately.
        // Use a silent error message that the UI can suppress.
        setTimeout(() => {
          optsRef.current.onSimliError?.("");
        }, 200);
      }, 100);
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
      setIsConnectedState(true);
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
      setIsConnectedState(false);
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
      setIsConnectedState(false);
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
    setIsConnectedState(false);
    clearResponseCommitTimer();
    // Cancel any queued audio chunks from the old connection.
    audioGenRef.current += 1;
    playbackQueueRef.current = Promise.resolve();
    e2eMsRef.current = null;
    try { audioCtxRef.current?.close(); } catch { /* may already be closed */ }
    audioCtxRef.current = null;
  }, []);

  const reconnect = useCallback((reconnectOpts?: { freshSession?: boolean }) => {
    if (reconnectOpts?.freshSession) {
      clearPersistedSession();
      freshSessionRef.current = true;
      setSessionKind(null);
    } else {
      freshSessionRef.current = false;
    }
    serverUrlRef.current = buildServerUrl();
    disconnect();
    manualDisconnectRef.current = false;
    connect();
  }, [buildServerUrl, connect, disconnect]);

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
              const nextTurn = store.turnNumber + 1;
              store.setTurnInfo(nextTurn, store.totalTurns);

              const mockVisualSteps = [
                { stepId: 1, stepLabel: "Sunlight", emoji: "☀️ → 🌿", caption: "Plants capture sunlight energy" },
                { stepId: 2, stepLabel: "Water + CO₂", emoji: "💧 + 🌬️ → 🌿", caption: "Roots absorb water; leaves take in CO₂" },
                { stepId: 3, stepLabel: "Chloroplast", emoji: "🌿🔬 [chloroplast]", caption: "Reactions happen inside chloroplasts" },
                { stepId: 4, stepLabel: "Glucose", emoji: "☀️💧🌬️ → 🍬 + O₂", caption: "Light energy converts to glucose" },
              ];
              const stepIdx = Math.min(nextTurn - 1, mockVisualSteps.length - 1);
              const step = mockVisualSteps[stepIdx];
              const isLast = nextTurn >= store.totalTurns;
              store.setVisual({
                diagramId: "photosynthesis",
                stepId: step.stepId,
                stepLabel: step.stepLabel,
                totalSteps: mockVisualSteps.length,
                highlightKeys: [step.stepLabel.toLowerCase()],
                unlockedElements: ["sunlight", "water", "carbon_dioxide", "leaf"].slice(0, stepIdx + 1),
                progressCompleted: Math.min(stepIdx + 1, 4),
                progressTotal: 4,
                progressLabel: `Photosynthesis Clues: ${Math.min(stepIdx + 1, 4)}/4`,
                caption: step.caption,
                emojiDiagram: step.emoji,
                turnNumber: nextTurn,
                isRecap: isLast,
              });

              setTimeout(() => {
                store.commitTutorResponse();
                if (isLast) {
                  setTimeout(() => {
                    store.setSessionComplete(true);
                  }, 200);
                }
              }, 400);
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
    e2eMsRef.current = null;              // Reset for new turn
    wsRef.current.send(JSON.stringify({ type: "end_of_utterance" }));
  }, []);

  const sendStartLesson = useCallback(() => {
    if (optsRef.current._useMock) {
      setTimeout(() => {
        const { store } = optsRef.current;
        store.startGreeting();
        const greeting = "Hey there! Plants make their own food — no kitchen needed. How do you think they pull that off?";
        const words = greeting.split(" ");
        for (const word of words) {
          store.appendStreamWord(word);
        }
        store.setVisual({
          diagramId: "photosynthesis",
          stepId: 0,
          stepLabel: "Introduction",
          totalSteps: 4,
          highlightKeys: ["intro"],
          unlockedElements: [],
          progressCompleted: 0,
          progressTotal: 4,
          progressLabel: "Photosynthesis Clues: 0/4",
          caption: "How do plants make food?",
          emojiDiagram: "🌱 + ☀️ → ❓",
          turnNumber: 0,
          isRecap: false,
        });
        setTimeout(() => {
          store.commitTutorResponse();
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

  const sendContinueLesson = useCallback(() => {
    if (optsRef.current._useMock) {
      // In mock mode, just transition to idle — no welcome-back simulation.
      setTimeout(() => optsRef.current.store.setMode("idle"), 200);
      return;
    }
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      console.debug(ts(), "[TutorSocket] sendContinueLesson: WS not open, skipping");
      return;
    }
    console.debug(ts(), "[TutorSocket] sendContinueLesson: sending continue_lesson");
    firstAudioPlayedRef.current = false;
    wsRef.current.send(JSON.stringify({ type: "continue_lesson" }));
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
    reconnect,
    sendAudioChunk,
    sendEndOfUtterance,
    sendStartLesson,
    sendContinueLesson,
    sendBargeIn,
    isConnected: isConnectedState,
    sessionKind,
    get ws() {
      return wsRef.current;
    },
  };
}
