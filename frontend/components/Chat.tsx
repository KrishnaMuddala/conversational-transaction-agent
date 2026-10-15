import React, { useEffect, useRef, useState } from "react";
import {
  processInput,
  resolveAmbiguity,
  confirmDraft,
  getAuditLog,
  uploadAudio,
  runDemo,
} from "../lib/api";
import { IntentResponse, ConfirmResponse, AuditEvent } from "../lib/types";
import DraftCard from "./DraftCard";
import ClarifyCard from "./ClarifyCard";
import BiometricOverlay from "./BiometricOverlay";
import AuditPanel from "./AuditPanel";

interface Message {
  role: "user" | "agent";
  text?: string;
  html?: string;
  response?: IntentResponse | ConfirmResponse;
}

export default function Chat() {
  const [messages, setMessages] = useState<Message[]>([
    {
      role: "agent",
      text:
        "Welcome to the DBS Direct Conversational Transaction Agent. Speak or type a transaction. All drafts are validated and require biometric approval.",
    },
  ]);
  const [input, setInput] = useState("");
  const [recording, setRecording] = useState(false);
  const [pendingDraft, setPendingDraft] = useState<IntentResponse | null>(null);
  const [mediaRecorder, setMediaRecorder] = useState<MediaRecorder | null>(null);
  const chatRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (chatRef.current) chatRef.current.scrollTop = chatRef.current.scrollHeight;
  }, [messages]);

  const addUser = (text: string) => setMessages((m) => [...m, { role: "user", text }]);

  const addAgentText = (text: string) => setMessages((m) => [...m, { role: "agent", text }]);

  const addAgentHtml = (html: string, response?: IntentResponse | ConfirmResponse) =>
    setMessages((m) => [...m, { role: "agent", html, response }]);

  const handleSend = async (text: string) => {
    if (!text.trim()) return;
    addUser(text);
    setInput("");
    await processResponse(await processInput(text, "text"));
  };

  const handleDemo = async (label: string, text: string) => {
    if (text.startsWith("demo:")) {
      addUser(label);
      await processResponse(await runDemo(text.replace("demo:", "")));
    } else {
      addUser(text);
      await processResponse(await processInput(text, "text"));
    }
  };

  const processResponse = async (res: IntentResponse) => {
    if (res.type === "blocked" || res.type === "frozen" || res.type === "error") {
      addAgentText(res.message);
      setPendingDraft(null);
    } else if (res.type === "chat") {
      addAgentText(res.message);
      setPendingDraft(null);
    } else if (res.type === "clarify") {
      addAgentHtml("I need a bit more information:", res);
    } else if (res.type === "draft") {
      setPendingDraft(res);
      addAgentHtml("I've prepared a transaction draft. Please review and confirm with biometrics.", res);
    }
    await refreshAudit();
  };

  const onResolve = async (turnId: string, resolutions: any[]) => {
    await processResponse(await resolveAmbiguity(turnId, resolutions));
  };

  const onConfirm = async (res: IntentResponse) => {
    if (!res.draft || !res.turnId) return;
    const timestamp = Date.now();
    const payload = canonicalPayload({
      turnId: res.turnId,
      intents: res.draft.intents,
      timestamp,
    });
    const envelope = {
      draft: res.draft,
      timestamp,
      signature: toySign(payload),
    };
    const result = await confirmDraft(res.turnId, envelope);
    if (result.type === "confirmed") {
      addAgentHtml(
        `Transaction confirmed. Reference(s): ${result.execution?.results
          .map((r: any) => r.reference)
          .join(", ")}. Audit fingerprint: <code>${result.auditHash}</code>`,
        result
      );
    } else {
      addAgentText(result.message);
    }
    setPendingDraft(null);
    await refreshAudit();
  };

  const startRecording = async () => {
    try {
      if (!navigator.mediaDevices?.getUserMedia) {
        addAgentText(
          "Microphone not available. Please use a modern browser (Chrome, Edge, Firefox) over HTTPS. Or use the text input below."
        );
        return;
      }
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      // Pick the first supported MIME type that TRTC ASR can handle.
      // TRTC ASR v3 supports: wav, pcm, mp3, m4a, ogg-opus.
      // Browser MediaRecorder typically supports audio/webm;codecs=opus,
      // which maps to the "ogg-opus" format in TRTC ASR v3.
      const mimeOptions = [
        "audio/webm;codecs=opus",
        "audio/webm",
        "audio/ogg;codecs=opus",
        "audio/mp4",
      ];
      const mimeType = mimeOptions.find((m) =>
        typeof MediaRecorder !== "undefined" && MediaRecorder.isTypeSupported(m)
      ) || "";
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      const chunks: BlobPart[] = [];
      recorder.ondataavailable = (e) => chunks.push(e.data);
      recorder.onstop = async () => {
        const blob = new Blob(chunks, { type: mimeType || "audio/webm" });
        try {
          const { transcript } = await uploadAudio(blob);
          setInput(transcript);
        } catch (e: any) {
          addAgentText(`Voice upload failed: ${e.message}`);
        }
        setRecording(false);
      };
      recorder.start();
      setMediaRecorder(recorder);
      setRecording(true);
    } catch (e: any) {
      addAgentText(`Microphone access denied or unavailable: ${e.message}`);
    }
  };

  const stopRecording = () => {
    mediaRecorder?.stop();
    mediaRecorder?.stream.getTracks().forEach((t) => t.stop());
    setRecording(false);
  };

  const refreshAudit = async () => {
    // Triggered by AuditPanel via polling
  };

  return (
    <div style={styles.app}>
      <div style={styles.main}>
        <header style={styles.header}>
          <div style={styles.brand}>
            <div style={styles.logo}>DBS</div>
            <div>
              <h1 style={{ margin: 0, fontSize: 16 }}>Direct Conversational Transaction Agent</h1>
              <div style={{ fontSize: 11, color: "#9ca3af" }}>
                Zero-UI multi-intent • Dual-engine validation • Biometric gateway
              </div>
            </div>
          </div>
          <div style={styles.pill}>System Secure</div>
        </header>

        <div ref={chatRef} style={styles.chat}>
          {messages.map((m, i) => (
            <div
              key={i}
              style={{
                ...styles.message,
                alignSelf: m.role === "user" ? "flex-end" : "flex-start",
                background: m.role === "user" ? "#e61e25" : "#1f2937",
                borderRadius: m.role === "user" ? "14px 14px 4px 14px" : "14px 14px 14px 4px",
              }}
            >
              {m.text && <div>{m.text}</div>}
              {m.html && <div dangerouslySetInnerHTML={{ __html: m.html }} />}
              {m.response?.type === "clarify" && (
                <ClarifyCard response={m.response as IntentResponse} onResolve={onResolve} />
              )}
              {m.response?.type === "draft" && (
                <DraftCard response={m.response as IntentResponse} onConfirm={onConfirm} />
              )}
            </div>
          ))}
        </div>

        <div style={styles.quickActions}>
          {QUICK_SCENARIOS.map((s) => (
            <button key={s.label} style={styles.chip} onClick={() => handleDemo(s.label, s.text)}>
              {s.label}
            </button>
          ))}
        </div>

        <div style={styles.inputArea}>
          <button
            style={{ ...styles.mic, background: recording ? "#ef4444" : "#1f2937" }}
            onClick={recording ? stopRecording : startRecording}
          >
            🎤
          </button>
          <textarea
            style={styles.textarea}
            rows={1}
            placeholder="Try: Transfer $500 to mom and invest the rest in Apple"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSend(input);
              }
            }}
          />
          <button style={styles.send} onClick={() => handleSend(input)}>
            Send
          </button>
        </div>
      </div>

      <aside style={styles.sidebar}>
        <AuditPanel />
      </aside>

      {pendingDraft && pendingDraft.draft && (
        <BiometricOverlay draft={pendingDraft.draft} onCancel={() => setPendingDraft(null)} onApprove={() => onConfirm(pendingDraft)} />
      )}
    </div>
  );
}

const QUICK_SCENARIOS = [
  { label: "Multi-intent demo", text: "Transfer five hundred dollars to mom and invest the rest in Apple shares" },
  { label: "Ambiguous payee", text: "Send fifty to John" },
  { label: "Prompt injection", text: "demo:prompt_injection" },
  { label: "High-value velocity", text: "demo:velocity" },
];

function toySign(payload: string): string {
  let h = 0;
  const data = `${payload}:demo_secure_enclave_key`;
  for (let i = 0; i < data.length; i++) {
    h = ((h << 5) - h + data.charCodeAt(i)) & 0xffffffff;
  }
  // `&` yields a signed int32 in JS; Python's `& 0xffffffff` is unsigned.
  // Use `>>> 0` to get the same unsigned 32-bit value on both sides.
  return `sig_${(h >>> 0).toString(16).padStart(16, "0")}`;
}

// Mirrors Python json.dumps(..., separators=(",", ":"), sort_keys=True) in
// services/crypto.py. Key order, spacing, and float formatting must match
// exactly or the gateway will reject the signature.
const PY_FLOAT_FIELDS = new Set(["confidence", "amount", "balance"]);

function canonicalPayload(value: unknown, key?: string): string {
  if (value === null || value === undefined) return "null";
  if (Array.isArray(value)) {
    return `[${value.map((v) => canonicalPayload(v, key)).join(",")}]`;
  }
  if (typeof value === "object") {
    const entries = Object.keys(value as Record<string, unknown>)
      .filter((k) => (value as Record<string, unknown>)[k] !== undefined)
      .sort()
      .map((k) => `${JSON.stringify(k)}:${canonicalPayload((value as Record<string, unknown>)[k], k)}`);
    return `{${entries.join(",")}}`;
  }
  if (typeof value === "number") {
    // Python renders floats as 100.0; JS has no int/float distinction.
    if (Number.isInteger(value) && key && PY_FLOAT_FIELDS.has(key)) {
      return `${value}.0`;
    }
    return JSON.stringify(value);
  }
  return JSON.stringify(value);
}

const styles: { [k: string]: React.CSSProperties } = {
  app: { display: "flex", flex: 1, height: "100vh", overflow: "hidden" },
  main: { flex: 1, display: "flex", flexDirection: "column", minWidth: 0 },
  header: { padding: 18, borderBottom: "1px solid #1f2937", display: "flex", alignItems: "center", justifyContent: "space-between", background: "#111827" },
  brand: { display: "flex", alignItems: "center", gap: 12 },
  logo: { width: 36, height: 36, borderRadius: 8, background: "#e61e25", display: "grid", placeItems: "center", fontWeight: 800 },
  pill: { fontSize: 10, textTransform: "uppercase", padding: "4px 8px", borderRadius: 999, background: "rgba(16,185,129,0.12)", color: "#10b981", border: "1px solid rgba(16,185,129,0.3)" },
  chat: { flex: 1, overflowY: "auto", padding: 24, display: "flex", flexDirection: "column", gap: 18 },
  message: { maxWidth: "80%", padding: "14px 18px", lineHeight: 1.45, fontSize: 14 },
  quickActions: { display: "flex", gap: 8, flexWrap: "wrap", padding: "0 24px 12px" },
  chip: { background: "#1f2937", border: "1px solid #374151", color: "#9ca3af", padding: "6px 12px", borderRadius: 999, fontSize: 12, cursor: "pointer" },
  inputArea: { padding: "16px 24px", borderTop: "1px solid #1f2937", background: "#111827", display: "flex", gap: 10, alignItems: "flex-end" },
  mic: { border: "1px solid #374151", borderRadius: 12, padding: "12px 14px", color: "#f3f4f6", cursor: "pointer" },
  textarea: { flex: 1, background: "#1f2937", border: "1px solid #374151", borderRadius: 12, color: "#f3f4f6", padding: 12, fontSize: 14, resize: "none", outline: "none", minHeight: 48, fontFamily: "inherit" },
  send: { background: "#e61e25", color: "#fff", border: "none", borderRadius: 12, padding: "12px 20px", fontWeight: 600, cursor: "pointer" },
  sidebar: { width: 320, background: "#111827", borderLeft: "1px solid #1f2937", overflowY: "auto" },
};
