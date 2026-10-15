export interface Account {
  id: string;
  type: string;
  balance: number;
  currency: string;
}

export interface Payee {
  id: string;
  name: string;
  bank: string;
  account: string;
}

export interface Asset {
  symbol: string;
  name: string;
}

export interface Intent {
  type: "transfer" | "invest" | "unknown";
  confidence: number;
  amount: number | null;
  amountDisplay: string | null;
  currency: string;
  sourceAccount: Account | null;
  destinationName: string | null;
  destination: Payee | Asset | null;
  destinationCandidates: (Payee | Asset)[];
  isRelativeAmount?: boolean;
  note?: string;
}

export interface Ambiguity {
  intentIndex: number;
  field: "payee_disambiguation" | "amount_resolution" | "account_selection";
  question: string;
  options: (Payee | Asset | Account)[];
}

export interface Draft {
  rawTranscript: string;
  intents: Intent[];
  ambiguities: Ambiguity[];
  signature: string | null;
}

export interface IntentResponse {
  type: "draft" | "clarify" | "frozen" | "blocked" | "chat" | "error";
  turnId: string;
  message: string;
  rawTranscript?: string;
  draft?: Draft;
  ambiguities?: Ambiguity[];
  validation?: { ok: boolean; issues: string[] };
}

export interface ConfirmResponse {
  type: "confirmed" | "rejected" | "error";
  turnId: string;
  message: string;
  execution?: { results: any[]; timestamp: number };
  auditHash?: string;
}

export interface AuditEvent {
  ts: number;
  turnId: string;
  event: string;
  payload: any;
}
