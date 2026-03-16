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
  /** No-op in custom mode; Simli audio is sent by the backend signaling bridge. */
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
export function useSimliWebRTC(opts: SimliWebRTCOptions): SimliWebRTC {
  const pcRef = useRef<RTCPeerConnection | null>(null);
  const connectedRef = useRef(false);

  // ── Stabilize opts via ref so callbacks don't depend on object identity ──
  // Without this, disconnect/connect are recreated every render because opts
  // is a new object each time, causing the cleanup useEffect to fire on every
  // re-render and destroy the active PeerConnection mid-negotiation.
  const optsRef = useRef(opts);
  optsRef.current = opts;

  const sendAudio = useCallback((_data: Uint8Array) => {
    // Custom Simli mode sends PCM through the backend's persistent signaling
    // WebSocket. The browser peer connection is recvonly video/audio.
  }, []);

  const disconnect = useCallback(() => {
    pcRef.current?.close();
    pcRef.current = null;
    connectedRef.current = false;
    optsRef.current.onClose?.();
  }, []);

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
      pcRef.current.close();
      pcRef.current = null;
      connectedRef.current = false;
    }

    console.log(ts(), "[SimliWebRTC] Starting WebRTC handshake...");

    // Match Simli's official P2P client: unified-plan + recvonly audio/video.
    const pc = new RTCPeerConnection({
      sdpSemantics: "unified-plan",
      iceServers: [
        { urls: "stun:stun.l.google.com:19302" },
      ],
    } as RTCConfiguration & { sdpSemantics?: string });
    pcRef.current = pc;

    // Receive avatar video + audio from Simli
    pc.addTransceiver("audio", { direction: "recvonly" });
    pc.addTransceiver("video", { direction: "recvonly" });

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
      return false;
    }

    // Send the gathered offer (with ICE candidates) to server for proxying to Simli
    const gatheredSdp = pc.localDescription?.sdp ?? offer.sdp;
    signalingWs.send(
      JSON.stringify({ type: "simli_sdp_offer", sdp: gatheredSdp })
    );
    console.log(ts(), "[SimliWebRTC] SDP offer sent to server");
    return true;
  }, [disconnect]);

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
