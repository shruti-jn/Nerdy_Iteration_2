import { useCallback, useEffect, useRef } from "react";
import { LogLevel, SimliClient } from "simli-client";

export interface SimliSdkSessionConfig {
  sessionToken: string;
  iceServers: RTCIceServer[] | null;
}

export interface SimliSdkOptions {
  getVideoElement: () => HTMLVideoElement | null;
  getAudioElement: () => HTMLAudioElement | null;
  onConnected?: () => void;
  onClose?: () => void;
  onError?: (message: string) => void;
}

export interface SimliSdkController {
  connect: () => Promise<boolean>;
  disconnect: () => Promise<void>;
  clearBuffer: () => void;
  sendAudio: (data: Uint8Array) => void;
  setSessionConfig: (config: SimliSdkSessionConfig) => void;
  readonly isConnected: boolean;
}

type SimliClientLike = {
  start: () => Promise<void>;
  stop?: () => Promise<void>;
  close?: () => Promise<void>;
  sendAudioData: (audioData: Uint8Array) => void;
  ClearBuffer?: () => void;
  on?: (event: string, cb: (...args: unknown[]) => void) => void;
};

function getClientErrorMessage(err: unknown): string {
  if (err instanceof Error && err.message.trim()) {
    return err.message;
  }
  return String(err);
}

export function useSimliSdk(opts: SimliSdkOptions): SimliSdkController {
  const clientRef = useRef<SimliClientLike | null>(null);
  const connectedRef = useRef(false);
  const sessionConfigRef = useRef<SimliSdkSessionConfig | null>(null);

  const setSessionConfig = useCallback((config: SimliSdkSessionConfig) => {
    sessionConfigRef.current = config;
  }, []);

  const disconnect = useCallback(async () => {
    const existing = clientRef.current;
    clientRef.current = null;
    connectedRef.current = false;

    if (!existing) {
      return;
    }

    try {
      if (typeof existing.stop === "function") {
        await existing.stop();
      } else if (typeof existing.close === "function") {
        await existing.close();
      }
    } catch (err) {
      console.warn("[SimliSDK] Failed to stop client cleanly:", err);
    } finally {
      opts.onClose?.();
    }
  }, [opts]);

  const connect = useCallback(async (): Promise<boolean> => {
    if (connectedRef.current) {
      return true;
    }

    const config = sessionConfigRef.current;
    const videoEl = opts.getVideoElement();
    const audioEl = opts.getAudioElement();

    if (!config || !videoEl || !audioEl) {
      return false;
    }

    await disconnect();

    try {
      const client = new SimliClient(
        config.sessionToken,
        videoEl,
        audioEl,
        config.iceServers,
        LogLevel.INFO,
        "p2p",
      ) as unknown as SimliClientLike;

      if (typeof client.on === "function") {
        client.on("start", () => {
          connectedRef.current = true;
          opts.onConnected?.();
        });
        client.on("stop", () => {
          connectedRef.current = false;
          opts.onClose?.();
        });
        client.on("error", (message?: unknown) => {
          connectedRef.current = false;
          opts.onError?.(
            typeof message === "string" && message.trim()
              ? message
              : "Simli SDK connection failed.",
          );
        });
        client.on("startup_error", (message?: unknown) => {
          connectedRef.current = false;
          opts.onError?.(
            typeof message === "string" && message.trim()
              ? message
              : "Simli SDK startup failed.",
          );
        });
      }

      clientRef.current = client;
      await client.start();
      connectedRef.current = true;
      opts.onConnected?.();
      return true;
    } catch (err) {
      clientRef.current = null;
      connectedRef.current = false;
      opts.onError?.(getClientErrorMessage(err));
      return false;
    }
  }, [disconnect, opts]);

  const sendAudio = useCallback((data: Uint8Array) => {
    const client = clientRef.current;
    if (!client || !connectedRef.current) {
      return;
    }
    client.sendAudioData(data);
  }, []);

  const clearBuffer = useCallback(() => {
    const client = clientRef.current;
    if (!client || typeof client.ClearBuffer !== "function") {
      return;
    }
    client.ClearBuffer();
  }, []);

  useEffect(() => {
    return () => {
      void disconnect();
    };
  }, [disconnect]);

  return {
    connect,
    disconnect,
    clearBuffer,
    sendAudio,
    setSessionConfig,
    get isConnected() {
      return connectedRef.current;
    },
  };
}
