import { useRef, useCallback, useEffect } from "react";

/** Returns a compact timestamp prefix: [HH:MM:SS.mmm] */
function ts(): string {
  const now = new Date();
  const hh = String(now.getHours()).padStart(2, "0");
  const mm = String(now.getMinutes()).padStart(2, "0");
  const ss = String(now.getSeconds()).padStart(2, "0");
  const ms = String(now.getMilliseconds()).padStart(3, "0");
  return `[${hh}:${mm}:${ss}.${ms}]`;
}

export interface SimliWebRTCOptions {
  /**
   * Getter that returns the current signaling WebSocket.
   * Called lazily inside connect() so it always gets the live socket,
   * even after Vite proxy reconnects replace the underlying WS instance.
   */
  getSignalingWs: () => WebSocket | null;
  /** Called when the remote MediaStream from Simli is ready to attach to a <video> */
  onStream: (stream: MediaStream) => void;
  /** Called when the connection closes or errors */
  onClose?: () => void;
  /** Skip real RTCPeerConnection (for testing). Default false. */
  _useMock?: boolean;
}

export interface SimliWebRTC {
  /**
   * Initiate the WebRTC handshake with Simli via the signaling server.
   * Returns true if the SDP offer was sent (handshake in progress),
   * false if it couldn't start (e.g. WebSocket not open — caller should retry).
   */
  connect(): Promise<boolean>;
  /** Close the peer connection */
  disconnect(): void;
  /** Send PCM Int16 audio data to Simli via the WebRTC DataChannel */
  sendAudio(data: Uint8Array): void;
  readonly isConnected: boolean;
}

/**
 * React hook that manages a WebRTC peer connection to Simli's avatar servers.
 *
 * Flow (v2 Simli API):
 *  1. Create RTCPeerConnection (ICE servers come from the server's Simli response)
 *  2. Add transceivers to receive avatar video+audio tracks
 *  3. Wait for ICE gathering to complete so the full offer is sent at once
 *  4. Send SDP offer to tutor-server via WebSocket, which proxies to Simli
 *  5. Server relays SDP answer + ICE servers back via custom window event
 *  6. Set remote description; ICE negotiation completes automatically
 *  7. ontrack fires → call opts.onStream(stream)
 */
// 10 ms of silence at 16 kHz mono PCM16 = 320 bytes (160 samples × 2 bytes).
// Sent periodically to prevent Simli from closing the DataChannel due to inactivity.
const SILENT_FRAME = new Uint8Array(320);
const DC_KEEPALIVE_INTERVAL_MS = 3_000;

export function useSimliWebRTC(opts: SimliWebRTCOptions): SimliWebRTC {
  const pcRef = useRef<RTCPeerConnection | null>(null);
  const dcRef = useRef<RTCDataChannel | null>(null);
  const connectedRef = useRef(false);

  // ── Stabilize opts via ref so callbacks don't depend on object identity ──
  // Without this, disconnect/connect are recreated every render because opts
  // is a new object each time, causing the cleanup useEffect to fire on every
  // re-render and destroy the active PeerConnection mid-negotiation.
  const optsRef = useRef(opts);
  optsRef.current = opts;

  // Track whether we've warned about DC not being open (avoid spamming console)
  const dcWarnedRef = useRef(false);

  // Keepalive interval for the DataChannel — sends silent PCM frames every 3 s
  // to prevent Simli from closing the DC due to inactivity between turns.
  const keepaliveRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopKeepalive = useCallback(() => {
    if (keepaliveRef.current !== null) {
      clearInterval(keepaliveRef.current);
      keepaliveRef.current = null;
    }
  }, []);

  const startKeepalive = useCallback(() => {
    stopKeepalive();
    keepaliveRef.current = setInterval(() => {
      const dc = dcRef.current;
      if (dc && dc.readyState === "open") {
        dc.send(SILENT_FRAME as unknown as Uint8Array<ArrayBuffer>);
      } else {
        // DC is no longer open — stop sending keepalives
        stopKeepalive();
      }
    }, DC_KEEPALIVE_INTERVAL_MS);
  }, [stopKeepalive]);

  const sendAudio = useCallback((data: Uint8Array) => {
    const dc = dcRef.current;
    if (dc && dc.readyState === "open") {
      dcWarnedRef.current = false;
      // Cast required: RTCDataChannel.send() types buffer as ArrayBuffer (not SharedArrayBuffer),
      // but Uint8Array's .buffer is typed as ArrayBufferLike in newer TS lib.dom.d.ts.
      dc.send(data as unknown as Uint8Array<ArrayBuffer>);
    } else if (!dcWarnedRef.current) {
      console.warn(ts(), "[SimliWebRTC] sendAudio: DataChannel not open (state:", dc?.readyState ?? "null", ") — audio dropped");
      dcWarnedRef.current = true;
    }
  }, []);

  const disconnect = useCallback(() => {
    stopKeepalive();
    dcRef.current?.close();
    dcRef.current = null;
    pcRef.current?.close();
    pcRef.current = null;
    connectedRef.current = false;
    optsRef.current.onClose?.();
  }, [stopKeepalive]);

  const connect = useCallback(async (): Promise<boolean> => {
    if (optsRef.current._useMock) {
      connectedRef.current = true;
      return true;
    }

    const signalingWs = optsRef.current.getSignalingWs();
    if (!signalingWs || signalingWs.readyState !== WebSocket.OPEN) {
      console.warn(ts(), "[SimliWebRTC] Signaling WebSocket not open — cannot connect");
      return false;
    }

    // Clean up any previous failed attempt before starting fresh
    if (pcRef.current) {
      console.log(ts(), "[SimliWebRTC] Cleaning up stale PeerConnection before reconnect");
      stopKeepalive();
      dcRef.current?.close();
      dcRef.current = null;
      pcRef.current.close();
      pcRef.current = null;
      connectedRef.current = false;
    }

    console.log(ts(), "[SimliWebRTC] Starting WebRTC handshake...");

    // Start with default STUN; server will provide Simli's ICE servers in the answer
    const pc = new RTCPeerConnection({
      iceServers: [
        { urls: "stun:stun.l.google.com:19302" },
      ],
    });
    pcRef.current = pc;

    // Create DataChannel for sending PCM audio to Simli (must be created
    // BEFORE the SDP offer so it's included in the offer's media description).
    // Simli's servers expect audio data on a DataChannel labelled "audio".
    const dc = pc.createDataChannel("audio", { ordered: true });
    dcRef.current = dc;

    dc.onopen = () => {
      console.log(ts(), "[SimliWebRTC] DataChannel open — ready to send audio");
      dcWarnedRef.current = false;
      startKeepalive();
    };
    dc.onclose = () => {
      console.warn(ts(), "[SimliWebRTC] DataChannel closed — lip-sync audio will be dropped until reconnect");
      stopKeepalive();
    };
    dc.onerror = (err) => console.error(ts(), "[SimliWebRTC] DataChannel error:", err);

    // Receive avatar video + audio from Simli
    pc.addTransceiver("video", { direction: "recvonly" });
    pc.addTransceiver("audio", { direction: "recvonly" });

    const remoteStream = new MediaStream();

    pc.ontrack = (event) => {
      // Use event.track directly — event.streams[0] may be undefined for
      // recvonly transceivers, causing tracks to silently not get added.
      remoteStream.addTrack(event.track);
      optsRef.current.onStream(remoteStream);
      console.log(ts(), "[SimliWebRTC] Received track:", event.track.kind);
    };

    pc.oniceconnectionstatechange = () => {
      console.log(ts(), "[SimliWebRTC] ICE state:", pc.iceConnectionState);
      if (pc.iceConnectionState === "connected") {
        connectedRef.current = true;
        console.log(ts(), "[SimliWebRTC] Fully connected!");
      } else if (pc.iceConnectionState === "failed" || pc.iceConnectionState === "closed") {
        disconnect();
      }
    };

    // Listen for SDP answer relayed from server via custom window event
    // The detail now includes { sdp, iceServers } from the new Simli flow
    const answerListener = (e: Event) => {
      console.debug(ts(), "[SimliWebRTC] simli:sdp-answer event received");
      const detail = (e as CustomEvent<{ sdp: string; iceServers?: RTCIceServer[] }>).detail;
      const sdp = typeof detail === "string" ? detail : detail.sdp;

      // Apply Simli's ICE servers (including TURN) so ICE negotiation succeeds
      // behind NATs. setConfiguration updates the config on an existing PC.
      if (typeof detail === "object" && detail.iceServers?.length) {
        console.log(ts(), "[SimliWebRTC] Applying Simli ICE servers:", detail.iceServers.length);
        try {
          pc.setConfiguration({ iceServers: detail.iceServers });
        } catch (cfgErr) {
          console.warn(ts(), "[SimliWebRTC] setConfiguration failed, continuing with default STUN:", cfgErr);
        }
      }

      console.debug(ts(), "[SimliWebRTC] Setting remote description (answer SDP len:", sdp?.length, ")");
      pc.setRemoteDescription({ type: "answer", sdp }).then(() => {
        console.debug(ts(), "[SimliWebRTC] Remote description set successfully");
      }).catch((err) => {
        console.error(ts(), "[SimliWebRTC] Failed to set remote description:", err);
      });
    };
    window.addEventListener("simli:sdp-answer", answerListener, { once: true });

    // Create offer and wait for ICE gathering to complete
    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);

    // Wait for ICE gathering to finish so we send a complete offer
    if (pc.iceGatheringState !== "complete") {
      await new Promise<void>((resolve) => {
        const check = () => {
          if (pc.iceGatheringState === "complete") {
            pc.removeEventListener("icegatheringstatechange", check);
            resolve();
          }
        };
        pc.addEventListener("icegatheringstatechange", check);
        // Safety timeout — don't wait forever
        setTimeout(resolve, 5000);
      });
    }

    // Verify the WS is still alive before sending (it may have died during ICE gathering)
    if (signalingWs.readyState !== WebSocket.OPEN) {
      console.warn(ts(), "[SimliWebRTC] WebSocket died during ICE gathering — aborting");
      pc.close();
      pcRef.current = null;
      dcRef.current = null;
      return false;
    }

    // Send the gathered offer (with ICE candidates) to server for proxying to Simli
    const gatheredSdp = pc.localDescription?.sdp ?? offer.sdp;
    signalingWs.send(
      JSON.stringify({ type: "simli_sdp_offer", sdp: gatheredSdp })
    );
    console.log(ts(), "[SimliWebRTC] SDP offer sent to server");
    return true;
  }, [disconnect, stopKeepalive, startKeepalive]);

  // Only clean up on unmount — disconnect is now stable (no deps on opts)
  // so this effect won't re-run on re-renders.
  useEffect(() => {
    return () => disconnect();
  }, [disconnect]);

  return {
    connect,
    disconnect,
    sendAudio,
    get isConnected() {
      return connectedRef.current;
    },
  };
}
