import React from "react";
import { Draft } from "../lib/types";

export default function BiometricOverlay({
  draft,
  onCancel,
  onApprove,
}: {
  draft: Draft;
  onCancel: () => void;
  onApprove: () => void;
}) {
  const total = draft.intents.reduce((sum, i) => sum + (i.amount || 0), 0);
  const from = draft.intents[0]?.sourceAccount?.type || "Savings";

  return (
    <div style={overlayStyle}>
      <div style={cardStyle}>
        <div style={iconStyle}>✋</div>
        <h2 style={{ margin: "0 0 8px" }}>Confirm Transaction</h2>
        <div style={{ color: "#9ca3af", fontSize: 14, marginBottom: 20 }}>
          {draft.intents.length} transaction{draft.intents.length > 1 ? "s" : ""} from {from}
        </div>
        <div style={{ fontSize: 28, fontWeight: 800, margin: "10px 0" }}>SGD {total.toFixed(2)}</div>
        <div style={{ fontSize: 11, color: "#10b981", margin: "14px 0" }}>
          🔒 Signed by device secure enclave • Agent has zero write access
        </div>
        <div style={{ display: "flex", gap: 10, marginTop: 16, justifyContent: "center" }}>
          <button style={cancelBtn} onClick={onCancel}>
            Cancel
          </button>
          <button style={approveBtn} onClick={onApprove}>
            Approve with Face ID
          </button>
        </div>
      </div>
    </div>
  );
}

const overlayStyle: React.CSSProperties = {
  position: "fixed",
  inset: 0,
  background: "rgba(0,0,0,0.7)",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  zIndex: 50,
};

const cardStyle: React.CSSProperties = {
  background: "#111827",
  border: "1px solid #374151",
  borderRadius: 18,
  padding: 28,
  width: "min(420px, 92vw)",
  textAlign: "center",
};

const iconStyle: React.CSSProperties = {
  width: 64,
  height: 64,
  borderRadius: "50%",
  background: "rgba(16,185,129,0.15)",
  color: "#10b981",
  display: "grid",
  placeItems: "center",
  margin: "0 auto 18px",
  fontSize: 28,
};

const cancelBtn: React.CSSProperties = {
  background: "transparent",
  color: "#9ca3af",
  border: "1px solid #374151",
  borderRadius: 12,
  padding: "12px 18px",
  cursor: "pointer",
};

const approveBtn: React.CSSProperties = {
  background: "#10b981",
  color: "#052e16",
  border: "none",
  borderRadius: 12,
  padding: "12px 18px",
  fontWeight: 600,
  cursor: "pointer",
};
