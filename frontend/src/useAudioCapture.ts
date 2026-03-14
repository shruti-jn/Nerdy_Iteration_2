import { useRef, useCallback, useEffect } from "react";

export interface AudioCaptureOptions {
  /** Called with each PCM Int16 chunk ready to send over WebSocket */
  onChunk: (chunk: ArrayBuffer) => void;
  /** Sample rate to request from AudioContext. Deepgram expects 16000. */
  sampleRate?: number;
  /** If true, skip real getUserMedia (for testing). Default false. */
  _useMock?: boolean;
}

export interface AudioCapture {
  /** Start capturing mic audio. Requests permission on first call. */
  start(): Promise<void>;
  /** Stop capturing and release mic. */
  stop(): void;
  readonly isActive: boolean;
}

/**
 * React hook that captures microphone audio via getUserMedia + AudioWorklet
 * and emits PCM Int16 chunks at 16 kHz mono.
 *
 * The AudioWorklet processor lives in /public/pcm-processor.js and is loaded
 * via addModule() so it runs off the main thread.
 */
export function useAudioCapture(opts: AudioCaptureOptions): AudioCapture {
  const activeRef = useRef(false);
  const streamRef = useRef<MediaStream | null>(null);
  const contextRef = useRef<AudioContext | null>(null);
  const workletNodeRef = useRef<AudioWorkletNode | null>(null);
  // ScriptProcessorNode fallback ref (deprecated API but universally supported)
  const scriptNodeRef = useRef<ScriptProcessorNode | null>(null);
  const sampleRate = opts.sampleRate ?? 16000;

  // Stabilize opts via ref so start() doesn't depend on object identity.
  // Without this, start is recreated every render, and the onChunk callback
  // captured during start() may reference a stale closure.
  const optsRef = useRef(opts);
  optsRef.current = opts;

  const stop = useCallback(() => {
    workletNodeRef.current?.disconnect();
    workletNodeRef.current = null;

    scriptNodeRef.current?.disconnect();
    scriptNodeRef.current = null;

    contextRef.current?.close().catch(() => undefined);
    contextRef.current = null;

    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;

    activeRef.current = false;
  }, []);

  const start = useCallback(async () => {
    if (activeRef.current) return;

    if (optsRef.current._useMock) {
      activeRef.current = true;
      return;
    }

    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        sampleRate,
        echoCancellation: true,
        noiseSuppression: true,
      },
    });
    streamRef.current = stream;

    const ctx = new AudioContext({ sampleRate });
    contextRef.current = ctx;

    const source = ctx.createMediaStreamSource(stream);

    // Try AudioWorklet first, fall back to ScriptProcessorNode if it fails.
    // AudioWorklet can fail if the browser blocks loading /pcm-processor.js
    // (CORS, mixed content, or browser-specific worklet restrictions).
    let workletLoaded = false;
    try {
      await ctx.audioWorklet.addModule("/pcm-processor.js");
      // stop() may have been called while addModule was awaiting — bail out.
      if (contextRef.current !== ctx) return;
      const workletNode = new AudioWorkletNode(ctx, "pcm-processor");
      workletNodeRef.current = workletNode;

      workletNode.port.onmessage = (e: MessageEvent<ArrayBuffer>) => {
        optsRef.current.onChunk(e.data);
      };

      source.connect(workletNode);
      workletLoaded = true;
      console.log("[AudioCapture] Using AudioWorklet path");
    } catch (workletErr) {
      if (contextRef.current !== ctx) return;
      console.warn("[AudioCapture] AudioWorklet failed, falling back to ScriptProcessor:", workletErr);
    }

    if (!workletLoaded) {
      if (contextRef.current !== ctx) return;
      // ScriptProcessorNode fallback — deprecated but works everywhere.
      // Buffer size 4096 ≈ 256ms at 16 kHz, matching the worklet.
      const bufferSize = 4096;
      const scriptNode = ctx.createScriptProcessor(bufferSize, 1, 1);
      scriptNodeRef.current = scriptNode;

      const int16Buf = new Int16Array(bufferSize);
      scriptNode.onaudioprocess = (ev: AudioProcessingEvent) => {
        const input = ev.inputBuffer.getChannelData(0);
        for (let i = 0; i < input.length; i++) {
          const s = Math.max(-1, Math.min(1, input[i]));
          int16Buf[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
        }
        // Copy and send — slice creates a new ArrayBuffer so the caller owns it
        optsRef.current.onChunk(int16Buf.buffer.slice(0));
      };

      source.connect(scriptNode);
      // ScriptProcessorNode requires connection to destination to fire events
      scriptNode.connect(ctx.destination);
      console.log("[AudioCapture] Using ScriptProcessor fallback path");
    }

    activeRef.current = true;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sampleRate]);

  // Clean up on unmount
  useEffect(() => {
    return () => stop();
  }, [stop]);

  return {
    start,
    stop,
    get isActive() {
      return activeRef.current;
    },
  };
}
