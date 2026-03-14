/**
 * Tests for useSimliWebRTC hook.
 *
 * Verifies:
 * - connect() returns false when signaling WebSocket is null or closed
 * - connect() creates RTCPeerConnection + DataChannel and sends SDP offer
 * - simli:sdp-answer event triggers setRemoteDescription and setConfiguration
 * - sendAudio() forwards bytes via DataChannel when open, no-ops otherwise
 * - disconnect() closes PeerConnection + DataChannel and fires onClose
 * - Mock mode: connect() returns true immediately without WebRTC
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useSimliWebRTC } from "./useSimliWebRTC";

// ── Mock DataChannel ──────────────────────────────────────────────────────

class MockDataChannel {
  readyState = "open";
  send = vi.fn();
  close = vi.fn();
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: ((e: unknown) => void) | null = null;
}

// ── Mock RTCPeerConnection ────────────────────────────────────────────────

class MockRTCPeerConnection {
  static instances: MockRTCPeerConnection[] = [];

  // Set to "complete" so the ICE-gathering await block is skipped entirely
  iceGatheringState = "complete";
  iceConnectionState = "new";
  localDescription: { sdp: string } | null = null;
  ontrack: ((e: unknown) => void) | null = null;
  oniceconnectionstatechange: (() => void) | null = null;

  _dc = new MockDataChannel();

  constructor(_config?: unknown) {
    MockRTCPeerConnection.instances.push(this);
  }

  createOffer = vi.fn(async () => ({ sdp: "v=0 mock-offer", type: "offer" as const }));
  setLocalDescription = vi.fn(async (desc: { sdp: string }) => {
    this.localDescription = desc;
  });
  setRemoteDescription = vi.fn(async () => {});
  setConfiguration = vi.fn();
  createDataChannel = vi.fn(() => this._dc);
  addTransceiver = vi.fn();
  close = vi.fn();
  removeEventListener = vi.fn();
  // Fire icegatheringstatechange listeners immediately when iceGatheringState is "complete"
  addEventListener = vi.fn((event: string, handler: () => void) => {
    if (event === "icegatheringstatechange" && this.iceGatheringState === "complete") {
      handler();
    }
  });
}

// ── Mock MediaStream ──────────────────────────────────────────────────────

class MockMediaStream {
  addTrack = vi.fn();
}

// ── Helpers ───────────────────────────────────────────────────────────────

function makeOpenWs(): WebSocket {
  return { readyState: 1 /* WebSocket.OPEN */, send: vi.fn() } as unknown as WebSocket;
}

// ── Setup / Teardown ──────────────────────────────────────────────────────

beforeEach(() => {
  MockRTCPeerConnection.instances = [];
  globalThis.RTCPeerConnection = MockRTCPeerConnection as unknown as typeof RTCPeerConnection;
  globalThis.MediaStream = MockMediaStream as unknown as typeof MediaStream;
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ── Tests ─────────────────────────────────────────────────────────────────

describe("useSimliWebRTC", () => {
  describe("connect()", () => {
    it("returns false when signaling WS is null", async () => {
      const { result } = renderHook(() =>
        useSimliWebRTC({ getSignalingWs: () => null, onStream: vi.fn() })
      );
      let ret: boolean | undefined;
      await act(async () => { ret = await result.current.connect(); });

      expect(ret).toBe(false);
      expect(MockRTCPeerConnection.instances).toHaveLength(0);
    });

    it("returns false when WS readyState is not OPEN", async () => {
      const closedWs = { readyState: 3, send: vi.fn() } as unknown as WebSocket;
      const { result } = renderHook(() =>
        useSimliWebRTC({ getSignalingWs: () => closedWs, onStream: vi.fn() })
      );
      let ret: boolean | undefined;
      await act(async () => { ret = await result.current.connect(); });

      expect(ret).toBe(false);
      expect(MockRTCPeerConnection.instances).toHaveLength(0);
    });

    it("creates PC + DataChannel, sends SDP offer via WS, returns true", async () => {
      const ws = makeOpenWs();
      const { result } = renderHook(() =>
        useSimliWebRTC({ getSignalingWs: () => ws, onStream: vi.fn() })
      );
      let ret: boolean | undefined;
      await act(async () => { ret = await result.current.connect(); });

      expect(ret).toBe(true);
      expect(MockRTCPeerConnection.instances).toHaveLength(1);

      const pc = MockRTCPeerConnection.instances[0];
      expect(pc.createDataChannel).toHaveBeenCalledWith("audio", { ordered: true });
      expect(pc.addTransceiver).toHaveBeenCalledWith("video", { direction: "recvonly" });
      expect(pc.addTransceiver).toHaveBeenCalledWith("audio", { direction: "recvonly" });

      expect((ws.send as ReturnType<typeof vi.fn>)).toHaveBeenCalledTimes(1);
      const sent = JSON.parse((ws.send as ReturnType<typeof vi.fn>).mock.calls[0][0] as string);
      expect(sent).toEqual({ type: "simli_sdp_offer", sdp: "v=0 mock-offer" });
    });

    it("returns true immediately in mock mode without creating RTCPeerConnection", async () => {
      const { result } = renderHook(() =>
        useSimliWebRTC({ getSignalingWs: () => null, onStream: vi.fn(), _useMock: true })
      );
      let ret: boolean | undefined;
      await act(async () => { ret = await result.current.connect(); });

      expect(ret).toBe(true);
      expect(MockRTCPeerConnection.instances).toHaveLength(0);
    });

    it("cleans up stale PeerConnection before reconnecting", async () => {
      const ws = makeOpenWs();
      const { result } = renderHook(() =>
        useSimliWebRTC({ getSignalingWs: () => ws, onStream: vi.fn() })
      );

      // First connect
      await act(async () => { await result.current.connect(); });
      const firstPc = MockRTCPeerConnection.instances[0];

      // Second connect — should close the first PC
      await act(async () => { await result.current.connect(); });
      expect(firstPc.close).toHaveBeenCalled();
      expect(MockRTCPeerConnection.instances).toHaveLength(2);
    });
  });

  describe("simli:sdp-answer event", () => {
    it("calls setRemoteDescription with the answer SDP", async () => {
      const ws = makeOpenWs();
      const { result } = renderHook(() =>
        useSimliWebRTC({ getSignalingWs: () => ws, onStream: vi.fn() })
      );
      await act(async () => { await result.current.connect(); });
      const pc = MockRTCPeerConnection.instances[0];

      act(() => {
        window.dispatchEvent(
          new CustomEvent("simli:sdp-answer", {
            detail: { sdp: "v=0 answer-sdp", iceServers: [] },
          })
        );
      });

      expect(pc.setRemoteDescription).toHaveBeenCalledWith({
        type: "answer",
        sdp: "v=0 answer-sdp",
      });
    });

    it("calls setConfiguration when non-empty iceServers are provided", async () => {
      const ws = makeOpenWs();
      const { result } = renderHook(() =>
        useSimliWebRTC({ getSignalingWs: () => ws, onStream: vi.fn() })
      );
      await act(async () => { await result.current.connect(); });
      const pc = MockRTCPeerConnection.instances[0];

      const iceServers = [{ urls: "stun:stun.l.google.com:19302" }];
      act(() => {
        window.dispatchEvent(
          new CustomEvent("simli:sdp-answer", {
            detail: { sdp: "v=0 answer", iceServers },
          })
        );
      });

      expect(pc.setConfiguration).toHaveBeenCalledWith({ iceServers });
    });

    it("does NOT call setConfiguration when iceServers is empty", async () => {
      const ws = makeOpenWs();
      const { result } = renderHook(() =>
        useSimliWebRTC({ getSignalingWs: () => ws, onStream: vi.fn() })
      );
      await act(async () => { await result.current.connect(); });
      const pc = MockRTCPeerConnection.instances[0];

      act(() => {
        window.dispatchEvent(
          new CustomEvent("simli:sdp-answer", {
            detail: { sdp: "v=0 answer", iceServers: [] },
          })
        );
      });

      expect(pc.setConfiguration).not.toHaveBeenCalled();
    });
  });

  describe("sendAudio()", () => {
    it("sends bytes via DataChannel when open", async () => {
      const ws = makeOpenWs();
      const { result } = renderHook(() =>
        useSimliWebRTC({ getSignalingWs: () => ws, onStream: vi.fn() })
      );
      await act(async () => { await result.current.connect(); });
      const dc = MockRTCPeerConnection.instances[0]._dc;

      const audio = new Uint8Array([1, 2, 3, 4]);
      act(() => { result.current.sendAudio(audio); });

      expect(dc.send).toHaveBeenCalledWith(audio);
    });

    it("is a no-op when DataChannel readyState is not 'open'", async () => {
      const ws = makeOpenWs();
      const { result } = renderHook(() =>
        useSimliWebRTC({ getSignalingWs: () => ws, onStream: vi.fn() })
      );
      await act(async () => { await result.current.connect(); });
      MockRTCPeerConnection.instances[0]._dc.readyState = "closed";

      act(() => { result.current.sendAudio(new Uint8Array([1, 2, 3])); });

      expect(MockRTCPeerConnection.instances[0]._dc.send).not.toHaveBeenCalled();
    });

    it("is a no-op before connect() is called (no crash)", () => {
      const { result } = renderHook(() =>
        useSimliWebRTC({ getSignalingWs: () => null, onStream: vi.fn() })
      );
      // Should not throw
      act(() => { result.current.sendAudio(new Uint8Array([1, 2, 3])); });
    });
  });

  describe("disconnect()", () => {
    it("closes PeerConnection and DataChannel", async () => {
      const ws = makeOpenWs();
      const { result } = renderHook(() =>
        useSimliWebRTC({ getSignalingWs: () => ws, onStream: vi.fn() })
      );
      await act(async () => { await result.current.connect(); });
      const pc = MockRTCPeerConnection.instances[0];
      const dc = pc._dc;

      act(() => { result.current.disconnect(); });

      expect(dc.close).toHaveBeenCalled();
      expect(pc.close).toHaveBeenCalled();
    });

    it("calls onClose callback", async () => {
      const ws = makeOpenWs();
      const onClose = vi.fn();
      const { result } = renderHook(() =>
        useSimliWebRTC({ getSignalingWs: () => ws, onStream: vi.fn(), onClose })
      );
      await act(async () => { await result.current.connect(); });
      act(() => { result.current.disconnect(); });

      expect(onClose).toHaveBeenCalled();
    });

    it("is safe to call before connect()", () => {
      const { result } = renderHook(() =>
        useSimliWebRTC({ getSignalingWs: () => null, onStream: vi.fn() })
      );
      // Should not throw
      act(() => { result.current.disconnect(); });
    });
  });
});
