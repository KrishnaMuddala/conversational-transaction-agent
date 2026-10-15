import React from "react";
import { IntentResponse } from "../lib/types";

export default function DraftCard({
  response,
  onConfirm,
}: {
  response: IntentResponse;
  onConfirm: (r: IntentResponse) => void;
}) {
  if (!response.draft) return null;

  const total = response.draft.intents.reduce((sum, i) => sum + (i.amount || 0), 0);

  return (
    <div style={cardStyle}>
      <h3 style={titleStyle}>📝 Transaction Draft</h3>
      {response.draft.intents.map((intent, idx) => (
        <div key={idx} style={rowStyle}>
          <span>
            <span style={{ ...badgeStyle, background: intent.type === "transfer" ? "rgba(59,130,246,0.15)" : "rgba(16,185,129,0.15)", color: intent.type === "transfer" ? "#93c5fd" : "#6ee7b7" }}>
              {intent.type}
            </span>
            {intent.sourceAccount?.type || "?"} →{" "}
            {intent.destination?.name || intent.destinationName || "?"}
          </span>
          <span>{intent.amountDisplay || "—"}</span>
        </div>
      ))}
      <div style={{ marginTop: 12, textAlign: "right", color: "#9ca3af", fontSize: 12 }}>
        Total: <strong style={{ color: "#f3f4f6" }}>SGD {total.toFixed(2)}</strong>
      </div>
      <div style={{ display: "flex", gap: 10, marginTop: 16 }}>
        <button style={confirmBtn} onClick={() => onConfirm(response)}>
          Confirm with Biometrics
        </button>
      </div>
    </div>
  );
}

const cardStyle: React.CSSProperties = {
  background: "#111827",
  border: "1px solid #374151",
  borderRadius: 14,
  padding: 16,
  marginTop: 12,
};

const titleStyle: React.CSSProperties = {
  margin: "0 0 12px",
  fontSize: 12,
  textTransform: "uppercase",
  letterSpacing: 0.5,
  color: "#9ca3af",
};

const rowStyle: React.CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  padding: "10px 0",
  borderBottom: "1px solid #374151",
};

const badgeStyle: React.CSSProperties = {
  fontSize: 10,
  padding: "3px 7px",
  borderRadius: 4,
  textTransform: "uppercase",
  fontWeight: 700,
  marginRight: 8,
};

const confirmBtn: React.CSSProperties = {
  background: "#10b981",
  color: "#052e16",
  border: "none",
  borderRadius: 12,
  padding: "12px 18px",
  fontWeight: 600,
  cursor: "pointer",
};
