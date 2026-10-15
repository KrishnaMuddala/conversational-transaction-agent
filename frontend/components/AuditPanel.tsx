import React, { useEffect, useState } from "react";
import { getAuditLog } from "../lib/api";
import { AuditEvent } from "../lib/types";

export default function AuditPanel() {
  const [events, setEvents] = useState<AuditEvent[]>([]);

  const refresh = async () => {
    try {
      const data = await getAuditLog(undefined, 200);
      setEvents(data);
    } catch (e) {
      console.error("Audit refresh failed", e);
    }
  };

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 3000);
    return () => clearInterval(id);
  }, []);

  return (
    <div style={{ padding: 18, fontSize: 12 }}>
      <h2 style={{ fontSize: 13, margin: "0 0 14px", display: "flex", justifyContent: "space-between" }}>
        Audit Ledger
        <span
          style={{
            fontSize: 9,
            padding: "4px 8px",
            borderRadius: 999,
            background: "rgba(16,185,129,0.12)",
            color: "#10b981",
            border: "1px solid rgba(16,185,129,0.3)",
          }}
        >
          {events.length} events
        </span>
      </h2>
      {events.length === 0 && <div style={{ color: "#9ca3af", textAlign: "center", marginTop: 40 }}>No events yet.</div>}
      {[...events].reverse().map((e, i) => {
        const payload = typeof e.payload === "object" ? JSON.stringify(e.payload).slice(0, 220) : String(e.payload);
        const important = ["SAFETY_BLOCK", "VALIDATION_FREEZE", "GATEWAY_REJECT"].includes(e.event);
        return (
          <div
            key={i}
            style={{
              padding: 10,
              marginBottom: 8,
              background: "#1f2937",
              borderLeft: `3px solid ${important ? "#ef4444" : "#3b82f6"}`,
              borderRadius: 6,
            }}
          >
            <div style={{ color: "#9ca3af", fontSize: 10, marginBottom: 4 }}>
              {new Date(e.ts).toLocaleTimeString()} · turn {e.turnId.slice(-6)}
            </div>
            <div style={{ fontWeight: 700 }}>{e.event}</div>
            <div style={{ color: "#9ca3af", marginTop: 4, wordBreak: "break-word" }}>
              {payload}
              {payload.length >= 220 ? "…" : ""}
            </div>
          </div>
        );
      })}
    </div>
  );
}
