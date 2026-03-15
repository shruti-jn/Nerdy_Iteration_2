import { useState, useCallback } from "react";
import type React from "react";
import type { SessionMode, AvatarConnectionState, AvatarProvider } from "../types";
import "./AvatarFeed.css";

interface Props {
  mode: SessionMode;
  avatarState: AvatarConnectionState;
  /** Ref to the <video> element that will receive the Simli WebRTC stream */
  videoRef?: React.Ref<HTMLVideoElement>;
  /** Called when the user clicks "Retry" after an avatar connection failure */
  onRetry?: () => void;
  /** Which avatar provider is active */
  avatarProvider?: AvatarProvider;
  /** Ref to the <div> container for SpatialReal's canvas */
  containerRef?: React.Ref<HTMLDivElement>;
}

export function AvatarFeed({ mode, avatarState, videoRef, onRetry, avatarProvider = "simli", containerRef }: Props) {
  const isSpeaking = mode === "tutor-responding" || mode === "tutor-greeting";
  const isListening = mode === "student-speaking";

  // Track whether the video stream is active via an event-driven state update.
  // Previously this was a plain variable (videoRef?.current?.srcObject != null)
  // which never triggered a re-render when srcObject was set externally.
  const [hasStream, setHasStream] = useState(false);

  const handlePlaying = useCallback(() => {
    console.debug("[AvatarFeed] Video playing event — stream active");
    setHasStream(true);
  }, []);
  const handleEnded = useCallback(() => {
    console.debug("[AvatarFeed] Video ended event — stream inactive");
    setHasStream(false);
  }, []);

  // Use avatarState === "live" as a fallback: when the MediaStream is
  // re-attached after a view transition (topic-select → getting-ready → lesson),
  // the <video> "playing" event may not fire again, leaving hasStream false.
  // avatarState is set to "live" in App.tsx when onStream fires, so it's a
  // reliable secondary signal that a live stream exists.
  const streamReady = hasStream || avatarState === "live";

  return (
    <div className="avatar-feed">
      <div
        className={[
          "avatar-feed__frame",
          isSpeaking && "avatar-feed__frame--speaking",
          isListening && "avatar-feed__frame--listening",
        ]
          .filter(Boolean)
          .join(" ")}
      >
        {/* Simli: WebRTC video — visible once a stream is attached to the ref */}
        {avatarProvider === "simli" && videoRef && (
          <video
            ref={videoRef}
            autoPlay
            playsInline
            muted
            onPlaying={handlePlaying}
            onEnded={handleEnded}
            className={[
              "avatar-feed__video",
              streamReady && "avatar-feed__video--active",
            ]
              .filter(Boolean)
              .join(" ")}
          />
        )}
        {/* SpatialReal: canvas container — SDK creates <canvas> inside this div */}
        {avatarProvider === "spatialreal" && containerRef && (
          <div
            ref={containerRef}
            className={[
              "avatar-feed__canvas-container",
              streamReady && "avatar-feed__canvas-container--active",
            ]
              .filter(Boolean)
              .join(" ")}
          />
        )}

        {/* Placeholder avatar — shown while no live stream is active */}
        <div
          className={[
            "avatar-feed__video-placeholder",
            streamReady && "avatar-feed__video-placeholder--hidden",
          ]
            .filter(Boolean)
            .join(" ")}
        >
          <AvatarPlaceholder mode={mode} avatarState={avatarState} onRetry={onRetry} />
        </div>

        {/* Status badge */}
        <div className={`avatar-feed__badge avatar-feed__badge--${mode}`}>
          {mode === "idle" && avatarState === "error" && <ErrorBadge />}
          {mode === "idle" && avatarState !== "live" && avatarState !== "error" && <ConnectingBadge />}
          {mode === "idle" && avatarState === "live" && <IdleDot />}
          {mode === "student-speaking" && <ListeningBadge />}
          {mode === "tutor-responding" && <SpeakingBadge />}
        </div>
      </div>
    </div>
  );
}

function AvatarPlaceholder({ mode, avatarState, onRetry }: { mode: SessionMode; avatarState: AvatarConnectionState; onRetry?: () => void }) {
  const isShimmer = avatarState === "connecting" || avatarState === "slow";

  return (
    <div className={`avatar-placeholder avatar-placeholder--${mode}`}>
      {/* Simulated avatar face */}
      <div
        className={[
          "avatar-placeholder__face",
          isShimmer && "avatar-placeholder__face--shimmer",
          avatarState === "error" && "avatar-placeholder__face--error",
        ]
          .filter(Boolean)
          .join(" ")}
      >
        {avatarState === "error" ? (
          <div className="avatar-placeholder__error-icon">!</div>
        ) : (
          <>
            <div className="avatar-placeholder__eyes">
              <div className="avatar-placeholder__eye" />
              <div className="avatar-placeholder__eye" />
            </div>
            <div
              className={[
                "avatar-placeholder__mouth",
                mode === "tutor-responding" && "avatar-placeholder__mouth--talking",
              ]
                .filter(Boolean)
                .join(" ")}
            />
          </>
        )}
      </div>
      <div className="avatar-placeholder__label">
        {avatarState === "error" ? "Avatar Unavailable" : "AI Tutor Avatar"}
      </div>
      {avatarState === "connecting" && (
        <div className="avatar-placeholder__sublabel">
          Setting up your session…
        </div>
      )}
      {avatarState === "slow" && (
        <div className="avatar-placeholder__sublabel avatar-placeholder__sublabel--slow">
          Your tutor is almost ready
          <br />
          This sometimes takes a few extra seconds.
        </div>
      )}
      {avatarState === "error" && (
        <div className="avatar-placeholder__sublabel avatar-placeholder__sublabel--error">
          Could not connect to avatar service.
          {onRetry && (
            <button
              type="button"
              className="avatar-placeholder__retry-btn"
              onClick={onRetry}
            >
              Retry
            </button>
          )}
        </div>
      )}
      {avatarState === "live" && (
        <div className="avatar-placeholder__sublabel" />
      )}
    </div>
  );
}

function ErrorBadge() {
  return (
    <div className="status-badge status-badge--error">
      <span className="status-badge__dot" />
      <span>Connection Failed</span>
    </div>
  );
}

function ConnectingBadge() {
  return (
    <div className="status-badge status-badge--connecting">
      <span className="status-badge__dot" />
      <span>Connecting</span>
    </div>
  );
}

function IdleDot() {
  return (
    <div className="status-badge status-badge--idle">
      <span className="status-badge__dot" />
      <span>Ready</span>
    </div>
  );
}

function ListeningBadge() {
  return (
    <div className="status-badge status-badge--listening">
      <span className="status-badge__dot" />
      <span>Listening…</span>
    </div>
  );
}

function SpeakingBadge() {
  return (
    <div className="status-badge status-badge--speaking">
      <span className="status-badge__dot" />
      <span>Responding</span>
    </div>
  );
}
