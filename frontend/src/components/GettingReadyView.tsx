import { useState, useEffect } from "react";
import type React from "react";
import type { AvatarConnectionState } from "../types";
import "./GettingReadyView.css";

interface Props {
  topic: string;
  avatarState: AvatarConnectionState;
  wsConnected: boolean;
  videoRef: React.RefObject<HTMLVideoElement>;
  onBack: () => void;
  onStart: () => void;
  /** Called when the <video> element starts playing — signals avatar is truly live */
  onVideoPlaying?: () => void;
}

export function GettingReadyView({ topic, avatarState, wsConnected, videoRef, onBack, onStart, onVideoPlaying }: Props) {
  const avatarReady = avatarState === "live";
  const allReady = wsConnected && avatarReady;

  console.debug("[GettingReady] render — ws:", wsConnected, "avatar:", avatarState, "allReady:", allReady);

  // Show fallback immediately on avatar error, or after 10s if still not live
  const [showFallback, setShowFallback] = useState(false);

  // Timer-based fallback: starts once and only resets if avatar goes live
  useEffect(() => {
    if (avatarReady) {
      console.debug("[GettingReady] Avatar is live — no fallback needed");
      return;
    }
    console.debug("[GettingReady] Starting 10s avatar fallback timer");
    const timer = setTimeout(() => {
      console.debug("[GettingReady] 10s fallback timer fired — showing 'Start without avatar'");
      setShowFallback(true);
    }, 10_000);
    return () => clearTimeout(timer);
  }, [avatarReady]);

  // Immediate fallback on avatar error (separate effect to avoid resetting the timer)
  useEffect(() => {
    if (avatarState === "error") {
      console.debug("[GettingReady] Avatar errored — showing fallback immediately");
      setShowFallback(true);
    }
  }, [avatarState]);

  const canStart = allReady || (wsConnected && showFallback);

  return (
    <div className="getting-ready">
      {/* Back button */}
      <button className="getting-ready__back" onClick={onBack} aria-label="Back to topic selection">
        <BackArrow />
        <span>Back</span>
      </button>

      <div className="getting-ready__content">
        {/* Topic heading */}
        <h1 className="getting-ready__topic">{topic}</h1>
        <p className="getting-ready__subtitle">Preparing your lesson...</p>

        {/* Avatar preview */}
        <div className="getting-ready__avatar-area">
          <video
            ref={videoRef}
            autoPlay
            playsInline
            muted
            onPlaying={onVideoPlaying}
            className={`getting-ready__video ${avatarReady ? "getting-ready__video--active" : ""}`}
          />
          {!avatarReady && (
            <div className="getting-ready__avatar-placeholder">
              <div className="getting-ready__face getting-ready__face--shimmer">
                <div className="getting-ready__eyes">
                  <div className="getting-ready__eye" />
                  <div className="getting-ready__eye" />
                </div>
                <div className="getting-ready__mouth" />
              </div>
            </div>
          )}
        </div>

        {/* Progress stepper */}
        <div className="getting-ready__steps">
          <Step label="Connecting to tutor" done={wsConnected} active={!wsConnected} />
          <Step label="Loading avatar" done={avatarReady} active={wsConnected && !avatarReady} />
          <Step label="Ready!" done={allReady} active={false} />
        </div>

        {/* Start Lesson button */}
        <button
          className={`getting-ready__start ${canStart ? "getting-ready__start--enabled" : ""}`}
          disabled={!canStart}
          onClick={onStart}
        >
          Start Lesson
        </button>

        {/* Fallback: start without avatar */}
        {showFallback && !avatarReady && wsConnected && (
          <button className="getting-ready__fallback" onClick={onStart}>
            Start without avatar
          </button>
        )}
      </div>
    </div>
  );
}

function Step({ label, done, active }: { label: string; done: boolean; active: boolean }) {
  return (
    <div className={`step ${done ? "step--done" : active ? "step--active" : "step--pending"}`}>
      <span className="step__icon">
        {done ? <CheckIcon /> : active ? <Spinner /> : <Circle />}
      </span>
      <span className="step__label">{label}</span>
    </div>
  );
}

function CheckIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <circle cx="8" cy="8" r="7" stroke="var(--accent)" strokeWidth="1.5" fill="rgba(45,212,191,0.1)" />
      <path d="M5 8l2 2 4-4" stroke="var(--accent)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function Spinner() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" className="step__spinner" aria-hidden="true">
      <circle cx="8" cy="8" r="6.5" stroke="var(--text-muted)" strokeWidth="1.5" opacity="0.3" />
      <path d="M14.5 8a6.5 6.5 0 00-6.5-6.5" stroke="var(--accent)" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

function Circle() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <circle cx="8" cy="8" r="6.5" stroke="var(--text-muted)" strokeWidth="1.5" opacity="0.3" />
    </svg>
  );
}

function BackArrow() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M10 12L6 8l4-4" />
    </svg>
  );
}
