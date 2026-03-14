export type SessionMode = "idle" | "student-speaking" | "tutor-responding" | "tutor-greeting";

export type AvatarConnectionState = "connecting" | "live" | "slow" | "error";

export type AppView = "topic-select" | "getting-ready" | "lesson";

export type TopicId = "photosynthesis" | "newtons_laws";

export interface TopicInfo {
  id: string;
  label: string;
  description: string;
  icon: string;
  available: boolean;
}

export interface ConversationEntry {
  id: string;
  role: "student" | "tutor";
  text: string;
  timestamp: number;
}

export interface StageLatency {
  stt_ms: number | null;
  llm_ms: number | null;
  tts_ms: number | null;
  total_ms: number | null;
}

export interface TurnLatency {
  turn: number;
  stt_ms: number | null;
  llm_ms: number | null;
  tts_ms: number | null;
  total_ms: number | null;
}

export interface SessionStore {
  view: AppView;
  mode: SessionMode;
  topic: string;
  topicId: TopicId | null;
  grade: number;
  turnNumber: number;
  totalTurns: number;
  /** True when the backend has signalled session_complete (all turns used). */
  sessionComplete: boolean;
  latencyMs: number | null;
  stageLatency: StageLatency | null;
  latencyHistory: TurnLatency[];
  history: ConversationEntry[];
  streamingWords: string[];
  /** User-visible error message (e.g. mic permission denied). Null when no error. */
  error: string | null;
  setView: (view: AppView) => void;
  setTopic: (id: TopicId, displayName: string) => void;
  setMode: (mode: SessionMode) => void;
  setLatency: (ms: number) => void;
  setStageLatency: (latency: StageLatency) => void;
  pushLatencyHistory: (entry: TurnLatency) => void;
  setError: (msg: string | null) => void;
  /** Update turn number and total from backend-provided values. */
  setTurnInfo: (turnNumber: number, totalTurns: number) => void;
  setSessionComplete: (complete: boolean) => void;
  addStudentUtterance: (text: string) => void;
  /** Replace the text of the most recent student entry (used to swap "…" placeholder with real transcript). */
  updateLastStudentUtterance: (text: string) => void;
  /** Remove the most recent student entry (used to clean up stale "…" placeholder on mic failure). */
  removeLastStudentUtterance: () => void;
  /** Begin the greeting turn — clears streaming words and sets mode to tutor-greeting. */
  startGreeting: () => void;
  startTutorResponse: () => void;
  appendStreamWord: (word: string) => void;
  commitTutorResponse: () => void;
  bargeIn: () => void;
  /** Restore session state from a server session_restore message. */
  restoreSession: (history: ConversationEntry[], turnNumber: number, totalTurns: number) => void;
  /** Reset all session state (for topic change / back navigation). */
  reset: () => void;
}
