import React, { useState } from "react";
import { IntentResponse, Payee, Asset, Account } from "../lib/types";

export default function ClarifyCard({
  response,
  onResolve,
}: {
  response: IntentResponse;
  onResolve: (turnId: string, resolutions: any[]) => void;
}) {
  const [amounts, setAmounts] = useState<{ [key: number]: string }>({});

  if (!response.draft || !response.ambiguities?.length) return null;

  return (
    <div style={cardStyle}>
      <h3 style={titleStyle}>❓ Clarification Needed</h3>
      {response.ambiguities.map((ambiguity, idx) => (
        <div key={idx} style={{ marginBottom: 18 }}>
          <p style={{ margin: "0 0 8px" }}>
            <strong>{ambiguity.question}</strong>
          </p>
          {ambiguity.options.length > 0 ? (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {ambiguity.options.map((opt, optIdx) => {
                const label = "name" in opt ? opt.name : "type" in opt ? (opt as Account).type : JSON.stringify(opt);
                const sub = "bank" in opt ? `${opt.bank} ${opt.account}` : "symbol" in opt ? (opt as Asset).symbol : "";
                return (
                  <button
                    key={optIdx}
                    style={optionBtn}
                    onClick={() => onResolve(response.turnId, [{ field: ambiguity.field, intentIndex: ambiguity.intentIndex, value: opt }])}
                  >
                    <strong>{label}</strong>
                    {sub && <div style={{ fontSize: 12, color: "#9ca3af" }}>{sub}</div>}
                  </button>
                );
              })}
            </div>
          ) : (
            <input
              style={inputStyle}
              placeholder="Type amount…"
              value={amounts[ambiguity.intentIndex] || ""}
              onChange={(e) => setAmounts({ ...amounts, [ambiguity.intentIndex]: e.target.value })}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  const val = parseFloat(amounts[ambiguity.intentIndex]?.replace(/[^0-9.]/g, "") || "");
                  if (!isNaN(val)) {
                    onResolve(response.turnId, [{ field: ambiguity.field, intentIndex: ambiguity.intentIndex, value: val }]);
                  }
                }
              }}
            />
          )}
        </div>
      ))}
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

const optionBtn: React.CSSProperties = {
  background: "#1f2937",
  border: "1px solid #374151",
  borderRadius: 8,
  padding: "10px 14px",
  color: "#f3f4f6",
  textAlign: "left",
  cursor: "pointer",
};

const inputStyle: React.CSSProperties = {
  background: "#1f2937",
  border: "1px solid #374151",
  borderRadius: 8,
  color: "#f3f4f6",
  padding: "10px 14px",
  width: "100%",
};
