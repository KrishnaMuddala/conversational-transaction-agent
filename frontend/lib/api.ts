import {
  IntentResponse,
  ConfirmResponse,
  AuditEvent,
  Draft,
} from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "/api";

async function post<T>(path: string, body: any): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.text();
    throw new Error(err || `HTTP ${res.status}`);
  }
  return res.json();
}

export async function processInput(rawTranscript: string, mode = "text"): Promise<IntentResponse> {
  return post<IntentResponse>("/intent", { rawTranscript, mode });
}

export async function resolveAmbiguity(turnId: string, resolutions: any[]): Promise<IntentResponse> {
  return post<IntentResponse>("/resolve", { turnId, resolutions });
}

export async function confirmDraft(turnId: string, envelope: { draft: Draft; timestamp: number; signature: string }): Promise<ConfirmResponse> {
  return post<ConfirmResponse>("/confirm", { turnId, envelope });
}

export async function getAuditLog(turnId?: string, limit = 100): Promise<AuditEvent[]> {
  const params = new URLSearchParams();
  if (turnId) params.set("turnId", turnId);
  params.set("limit", String(limit));
  const res = await fetch(`${API_BASE}/audit?${params.toString()}`);
  if (!res.ok) throw new Error("Failed to load audit log");
  return res.json();
}

export async function uploadAudio(blob: Blob): Promise<{ transcript: string }> {
  // Determine file extension from the blob's MIME type so the backend
  // can route it to the correct TRTC ASR voice_format.
  const ext = blob.type.includes("webm")
    ? "webm"
    : blob.type.includes("ogg")
      ? "ogg"
      : blob.type.includes("mp4")
        ? "m4a"
        : blob.type.includes("wav")
          ? "wav"
          : "webm";
  const form = new FormData();
  form.append("file", blob, `voice.${ext}`);
  const res = await fetch(`${API_BASE}/asr`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    const detail = await res.text();
    let parsed: any = null;
    try {
      parsed = JSON.parse(detail);
    } catch {}
    throw new Error(
      `ASR failed (HTTP ${res.status})${parsed?.detail ? `: ${parsed.detail}` : detail ? `: ${detail.slice(0, 200)}` : ""}`,
    );
  }
  return res.json();
}

export async function runDemo(scenario: string): Promise<IntentResponse> {
  return post<IntentResponse>(`/demo/${scenario}`, {});
}
