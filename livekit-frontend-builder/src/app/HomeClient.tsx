"use client";

import { useState, useCallback, useEffect, useRef } from "react";
import {
  LiveKitRoom,
  useVoiceAssistant,
  RoomAudioRenderer,
  useDataChannel,
} from "@livekit/components-react";

function getLiveKitUrl(): string {
  if (typeof window === "undefined") return "wss://localhost:5443/livekit-ws/";
  return `wss://${window.location.host}/livekit-ws/`;
}
const LIVEKIT_URL = getLiveKitUrl();
const TOKEN_URL = process.env.NEXT_PUBLIC_TOKEN_URL || "/api/token";

interface TranscriptEntry {
  role: "user" | "agent";
  text: string;
  isFunctionCall?: boolean;
}

interface IvaState {
  stage: string;
  slots_extracted: Record<string, string | null>;
  slots_accumulated: Record<string, string | null>;
  sentiment: string;
  call_complete: boolean;
  escalated: boolean;
  stage_changed: boolean;
}

const STAGE_LABELS: Record<string, string> = {
  greeting: "Greeting",
  verification: "Member Verification",
  collect_pickup: "Collecting Pickup Address",
  collect_pickup_time: "Collecting Pickup Time",
  collect_destination: "Collecting Destination",
  collect_dropoff_time: "Collecting Drop-off Time",
  collect_special_needs: "Special Needs Assessment",
  confirm_booking: "Confirming Booking",
  complete: "Call Complete",
  escalate: "Escalating to Agent",
  farewell: "Farewell",
};

const SLOT_LABELS: Record<string, string> = {
  member_id: "Member ID",
  member_name: "Member Name",
  date_of_birth: "Date of Birth",
  pickup_address: "Pickup Address",
  pickup_time: "Pickup Time",
  pickup_date: "Pickup Date",
  destination_address: "Destination",
  destination_name: "Destination Name",
  dropoff_time: "Drop-off Time",
  appointment_time: "Appointment Time",
  special_needs: "Special Needs",
  wheelchair: "Wheelchair",
  mobility_aid: "Mobility Aid",
  attendant: "Attendant",
  round_trip: "Round Trip",
  notes: "Notes",
};

function formatStageName(stage: string): string {
  return STAGE_LABELS[stage] || stage.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function formatSlotKey(key: string): string {
  return SLOT_LABELS[key] || key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function getSentimentColor(sentiment: string): string {
  switch (sentiment?.toLowerCase()) {
    case "positive":
    case "happy":
      return "positive";
    case "frustrated":
    case "impatient":
      return "frustrated";
    case "angry":
      return "angry";
    case "confused":
      return "confused";
    default:
      return "neutral";
  }
}

export default function Home() {
  const [token, setToken] = useState<string | null>(null);
  const [connecting, setConnecting] = useState(false);

  const handleConnect = useCallback(async () => {
    setConnecting(true);
    try {
      const resp = await fetch(TOKEN_URL);
      const data = await resp.json();
      setToken(data.token);
    } catch (e) {
      console.error("Failed to get token:", e);
      setConnecting(false);
    }
  }, []);

  const handleDisconnect = useCallback(() => {
    setToken(null);
    setConnecting(false);
  }, []);

  if (!token) {
    return (
      <div className="app-container">
        <div className="landing">
          <div className="landing-icon">
            <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z" />
            </svg>
          </div>
          <h1>NEMT Voice Assistant</h1>
          <p className="landing-desc">
            Book non-emergency medical transportation rides with our voice assistant.
            Speak naturally to provide your member ID, pickup and destination details,
            and any special accommodation needs.
          </p>
          <button
            className="start-call-btn"
            onClick={handleConnect}
            disabled={connecting}
          >
            {connecting ? "Connecting..." : "Start Call"}
          </button>
          <p className="landing-footer">
            Powered by Intelepeer Livekit Agent
          </p>
        </div>
      </div>
    );
  }

  return (
    <LiveKitRoom
      serverUrl={LIVEKIT_URL}
      token={token}
      connect={true}
      audio={true}
      onDisconnected={handleDisconnect}
    >
      <RoomAudioRenderer />
      <CallUI onDisconnect={handleDisconnect} />
    </LiveKitRoom>
  );
}

function CallUI({ onDisconnect }: { onDisconnect: () => void }) {
  const { state } = useVoiceAssistant();
  const [transcripts, setTranscripts] = useState<TranscriptEntry[]>([]);
  const [ivaState, setIvaState] = useState<IvaState | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Listen for transcript data
  const onTranscriptReceived = useCallback((payload: Uint8Array) => {
    try {
      const text = new TextDecoder().decode(payload);
      const msg = JSON.parse(text);
      if (msg.type === "transcript") {
        setTranscripts((prev) => [
          ...prev,
          { role: msg.role, text: msg.text, isFunctionCall: msg.isFunctionCall },
        ]);
      }
    } catch {
      // ignore
    }
  }, []);

  // Listen for IVA state data
  const onIvaStateReceived = useCallback((payload: Uint8Array) => {
    try {
      const text = new TextDecoder().decode(payload);
      const msg = JSON.parse(text);
      setIvaState(msg);
    } catch {
      // ignore
    }
  }, []);

  useDataChannel("transcripts", onTranscriptReceived);
  useDataChannel("iva_state", onIvaStateReceived);

  // Auto-scroll transcript
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [transcripts]);

  const statusText =
    state === "listening" ? "Listening..."
    : state === "thinking" ? "Thinking..."
    : state === "speaking" ? "Speaking..."
    : state === "connecting" ? "Connecting..."
    : "Connected";

  const dotClass =
    state === "disconnected" ? "disconnected"
    : state === "connecting" ? "connecting"
    : state === "listening" ? "listening"
    : state === "speaking" ? "speaking"
    : "";

  // Build accumulated slots (only non-null values)
  const slots = ivaState?.slots_accumulated || ivaState?.slots_extracted || {};
  const filledSlots = Object.entries(slots).filter(
    ([, v]) => v !== null && v !== undefined && v !== ""
  );

  return (
    <div className="app-container">
      {/* Header bar */}
      <header className="header">
        <div style={{ display: "flex", alignItems: "baseline" }}>
          <span className="header-title">NEMT Voice Assistant</span>
          <span className="header-subtitle">Ride Booking</span>
        </div>
        <div className="header-status">
          <span className={`status-dot ${dotClass}`} />
          {statusText}
        </div>
      </header>

      {/* Main layout: transcript + sidebar */}
      <div className="call-layout">
        {/* Transcript panel */}
        <div className="transcript-panel">
          <div className="transcript-header">Conversation</div>
          <div className="transcript-body" ref={scrollRef}>
            {transcripts.length === 0 && (
              <p className="transcript-empty">
                The assistant will greet you shortly. Speak naturally to book your ride.
              </p>
            )}
            {transcripts.map((entry, i) => (
              <div key={i} className="transcript-entry">
                <span className={`role ${entry.role}`}>
                  {entry.role === "user" ? "CALLER" : "AGENT"}
                </span>
                <span className="text">{entry.text}</span>
                {entry.isFunctionCall && (
                  <div className="tool-badge">System Action</div>
                )}
              </div>
            ))}
          </div>
          <div className="call-controls">
            <button className="end-call-btn" onClick={onDisconnect}>
              End Call
            </button>
          </div>
        </div>

        {/* IVA Status sidebar */}
        <aside className="iva-sidebar">
          <div className="iva-sidebar-header">Call Status</div>

          {/* Stage */}
          <div className="iva-section">
            <div className="iva-section-label">Current Stage</div>
            <div className="iva-stage">
              {ivaState ? formatStageName(ivaState.stage) : "Waiting..."}
            </div>
          </div>

          {/* Sentiment */}
          <div className="iva-section">
            <div className="iva-section-label">Caller Sentiment</div>
            <div className="iva-sentiment">
              <span className={`sentiment-dot ${getSentimentColor(ivaState?.sentiment || "neutral")}`} />
              {ivaState?.sentiment
                ? ivaState.sentiment.charAt(0).toUpperCase() + ivaState.sentiment.slice(1)
                : "Neutral"}
            </div>
          </div>

          {/* Badges */}
          {(ivaState?.call_complete || ivaState?.escalated) && (
            <div className="iva-section">
              <div className="iva-section-label">Status</div>
              <div className="badges-row">
                {ivaState.call_complete && (
                  <span className="badge badge-complete">Call Complete</span>
                )}
                {ivaState.escalated && (
                  <span className="badge badge-escalated">Escalated</span>
                )}
              </div>
            </div>
          )}

          {/* Collected Slots */}
          <div className="iva-section">
            <div className="iva-section-label">
              Information Collected ({filledSlots.length})
            </div>
            {filledSlots.length === 0 ? (
              <p style={{ color: "#94a3b8", fontSize: "0.85rem", fontStyle: "italic" }}>
                No data collected yet
              </p>
            ) : (
              <div className="slots-list">
                {filledSlots.map(([key, value]) => (
                  <div key={key} className="slot-row">
                    <span className="slot-key">{formatSlotKey(key)}</span>
                    <span className="slot-value">{String(value)}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </aside>
      </div>
    </div>
  );
}
