"""
Generates the DCTA hackathon deck from the codebase facts in
ARCHITECTURE.md, STATUS.md, review.md, and the eval set.
Output: Deck/DBS-DCTA-Deck.pptx
"""

from __future__ import annotations

from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.util import Emu, Pt

BASE = Path(__file__).resolve().parent
FRAMES = BASE / "shots"

# palette (DBS-ish teal / deep navy / warning amber)
NAVY = RGBColor(0x0B, 0x14, 0x21)
TEAL = RGBColor(0x00, 0x82, 0x86)
LIGHT = RGBColor(0x11, 0x1B, 0x2C)
PALE = RGBColor(0xE8, 0xEF, 0xF1)
AMBER = RGBColor(0xC9, 0x7A, 0x1A)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
GREY = RGBColor(0x9F, 0xA9, 0xAF)
GREEN = RGBColor(0x2E, 0x8B, 0x57)
RED = RGBColor(0xB0, 0x3A, 0x2E)

SW = Emu(12192000)  # 16:9 width
SH = Emu(6858000)   # 16:9 height


def new_deck() -> Presentation:
    prs = Presentation()
    prs.slide_width = SW
    prs.slide_height = SH
    return prs


def add_slide(prs: Presentation) -> object:
    return prs.slides.add_slide(prs.slide_layouts[6])  # blank


def bg(slide, color: RGBColor):
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = color


def box(slide, x, y, w, h, fill=None, line=None):
    shp = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,
                                 Emu(int(x)), Emu(int(y)), Emu(int(w)), Emu(int(h)))
    if fill:
        shp.fill.solid()
        shp.fill.fore_color.rgb = fill
    else:
        shp.fill.background()
    if line:
        shp.line.color.rgb = line
        shp.line.width = Pt(1)
    else:
        shp.line.fill.background()
    shp.shadow.inherit = False
    return shp


def text(slide, x, y, w, h, runs, size=14, color=WHITE, bold=False,
         align=PP_ALIGN.LEFT, font="Calibri", anchor=MSO_ANCHOR.TOP,
         space_after=4, line_spacing=1.0):
    tb = slide.shapes.add_textbox(Emu(int(x)), Emu(int(y)), Emu(int(w)), Emu(int(h)))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    if isinstance(runs, str):
        runs = [(runs, size, color, bold)]
    first = True
    for item in runs:
        inner = item if isinstance(item, tuple) else (item, size, color, bold)
        t, sz, col, bd = inner
        p = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        p.alignment = align
        p.space_after = Pt(space_after)
        p.line_spacing = line_spacing
        r = p.add_run()
        r.text = t
        r.font.size = Pt(sz)
        r.font.color.rgb = col
        r.font.bold = bd
        r.font.name = font
    return tb


def chip(slide, x, y, label, fill=TEAL, size=11, w=0, h=300000):
    pad = 24000
    ww = w if w else (len(label) * size * 900 + 180000)
    c = box(slide, x, y, ww, h, fill=fill)
    tf = c.text_frame
    tf.word_wrap = False
    tf.margin_left = pad
    tf.margin_right = pad
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    r = p.add_run(); r.text = label
    r.font.size = Pt(size); r.font.color.rgb = WHITE; r.font.bold = True
    return ww


def header(slide, num, title, sub=None):
    box(slide, 0, 0, 312000, 210000, fill=NAVY)
    text(slide, 360000, 220000, 11200000, 640000, title, size=30, bold=True, color=WHITE)
    if sub:
        text(slide, 630000, 520000, 11000000, 320000, sub, size=13, color=GREY)
    text(slide, 11500000, 160000, 500000, 200000, str(num), size=16, color=GREY)
    box(slide, 630000, 930000, 10800000, 8000, fill=TEAL)


def footer(slide, note="DBS DCTA — direct conversational transaction agent"):
    text(slide, 630000, 6480000, 10500000, 220000, note, size=10, color=GREY)


def bullets(slide, x, y, w, h, items, size=15, gap=8, color=PALE, glyph="\u2022"):
    lines = []
    for it in items:
        if isinstance(it, tuple):
            lead, rest = it
            lines.append(("\u2003".join([glyph, lead]), size, TEAL, True))
            lines.append((rest, size, color, False))
        else:
            lines.append((f"{glyph}  {it}", size, color, False))
    return text(slide, x, y, w, h, lines, size=size, space_after=gap, line_spacing=1.05)


def stat_card(slide, x, y, w, big, label, big_color=TEAL):
    box(slide, x, y, w, 1060000, fill=LIGHT)
    text(slide, x + 140000, y + 140000, w - 280000, 520000, big,
         size=40, bold=True, color=big_color)
    text(slide, x + 140000, y + 660000, w - 280000, 320000, label,
         size=12, color=GREY)


def photo(slide, path, x, y, w, h):
    """Insert an image centered in the (x,y,w,h) box, preserving aspect."""
    from PIL import Image
    with Image.open(path) as im:
        ar = im.width / im.height
    box_ar = w / h
    if ar > box_ar:
        pw = w
        ph = int(w / ar)
    else:
        ph = h
        pw = int(h * ar)
    px = int(x + (w - pw) / 2)
    py = int(y + (h - ph) / 2)
    slide.shapes.add_picture(path, Emu(px), Emu(py), Emu(pw), Emu(ph))


def section_slide(prs, num, kicker, title, points):
    s = add_slide(prs)
    bg(s, NAVY)
    box(s, 0, 0, 312000, 210000, fill=TEAL)
    text(s, 630000, 1700000, 10800000, 400000, f"{num} — {kicker}", size=16, color=TEAL, bold=True)
    text(s, 630000, 2150000, 10800000, 900000, title, size=42, bold=True, color=WHITE)
    bullets(s, 630000, 3300000, 10600000, 2500000, points, size=17, gap=14)
    footer(s)
    return s


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------
def build(path: str) -> None:
    prs = new_deck()

    # Slide 1 — title
    s = add_slide(prs)
    bg(s, NAVY)
    box(s, 0, 0, 312000, 210000, fill=TEAL)
    text(s, 630000, 1850000, 11000000, 1100000, "DBS DCTA", size=64, bold=True, color=WHITE)
    text(s, 630000, 3000000, 11000000, 500000,
         "Direct Conversational Transaction Agent", size=28, color=TEAL, bold=True)
    text(s, 630000, 3600000, 11000000, 400000,
         "Spoken or typed instruction \u2192 validated, biometric-confirmed transaction draft",
         size=15, color=PALE)
    box(s, 630000, 4400000, 10800000, 4000, fill=GREY)
    text(s, 630000, 4650000, 11000000, 800000,
         "Five-layer zero-trust pipeline \u00b7 Tencent Cloud (ADP, TRTC ASR, TTS, KMS, COS) \u00b7 PostgreSQL audit chain",
         size=15, color=GREY)
    footer(s, "DBS DCTA — direct conversational transaction agent")

    # Slide 2 — section: problem & idea
    section_slide(prs, "01", "Problem & Idea",
                  "Banking through a conversational agent the user can trust",
                  ["Voice and text instructions must reach a confirmable draft only when they are genuine transactions",
                   "A conversational LLM must never quietly execute anything \u2014 no model is allowed to be the final gate",
                   "Every step (parse, ambiguity, validation, gateway, execution) is an auditable, independent layer",
                   "Tencent Cloud provides the intelligence (ADP), voice (TRTC ASR / TTS), signing (KMS), archive (COS) and ledger (TDSQL-C / PostgreSQL)"])

    # Slide 3 — runtime topology
    s = add_slide(prs)
    bg(s, NAVY)
    header(s, "02", "Runtime topology", "Four containers, one entry point \u2014 only nginx faces the user")
    # nginx bar
    box(s, 630000, 1500000, 10800000, 720000, fill=TEAL)
    text(s, 630000, 1540000, 10800000, 300000, "user \u2192 HTTP \u2192  nginx (1.27-alpine)   :8080 \u2192 :80",
         size=17, bold=True, color=WHITE, align=PP_ALIGN.CENTER)
    text(s, 630000, 1880000, 10800000, 260000, "/ \u2192 frontend:3000      /api/* \u2192 backend:8000 (strips /api)",
         size=12, color=PALE, align=PP_ALIGN.CENTER)
    # frontend / backend
    box(s, 730000, 3200000, 5400000, 1200000, fill=LIGHT)
    text(s, 980000, 3350000, 4800000, 350000, "frontend", size=20, bold=True, color=WHITE)
    text(s, 980000, 3750000, 4800000, 500000,
         [("Next.js 14.2 \u00b7 React 18 \u00b7 TS 5.4", 13, PALE, False),
          ("Chat.tsx  \u00b7 lib/api.ts  \u00b7 lib/types.ts", 12, GREY, False),
          ("draft review \u00b7 mic capture \u00b7 confirm button", 12, GREY, False)])
    box(s, 6500000, 3200000, 4900000, 1200000, fill=LIGHT)
    text(s, 6760000, 3350000, 4400000, 350000, "backend — FastAPI / Uvicorn", size=20, bold=True, color=WHITE)
    text(s, 6760000, 3750000, 4400000, 500000,
         [("main.py (REST) \u00b7 models.py (Pydantic)", 13, PALE, False),
          ("services/: parser, shield, validator, accounts, crypto, asr, tts", 12, GREY, False),
          ("audit/logger.py \u00b7 ledger/executor.py", 12, GREY, False)])
    # external row
    text(s, 630000, 4850000, 3000000, 300000, "Tencent Cloud & data plane", size=13, bold=True, color=TEAL)
    chips = [
        ("ADP  parse", 630000), ("TRTC  voice", 2620000), ("TTS  audio", 4560000),
        ("KMS  sign", 6500000), ("COS  archive", 8440000), ("PostgreSQL  audit", 10100000),
    ]
    for label, x in chips:
        w = chip(s, x, 5300000, label, h=420000, size=13)
    box(s, 630000, 6200000, 10800000, 4000, fill=GREY)
    footer(s)

    # Slide 4 — five layers
    s = add_slide(prs)
    bg(s, NAVY)
    header(s, "03", "Five-layer zero-trust pipeline", "No single component is trusted \u2014 the model proposes, code disposes")
    layers = [
        ("L0  Audit", "append-only, hash-chained events \u2192 PostgreSQL", TEAL),
        ("L2  Parser (ADP)", "utterance \u2192 Intent[] \u00b7 not trusted for ids/balances/identity", TEAL),
        ("L2a No-intent gate", "empty intent \u2192 chat, stop \u2014 chitchat can never become a draft", TEAL),
        ("L1  Safety shield", "raw-transcript injection + account-number block", AMBER),
        ("L2b Registry backfill", "balance/payee/asset identity overwritten from authoritative registry", TEAL),
        ("L3  Validation agent", "re-derives amount independently \u2192 freeze on discrepancy", AMBER),
        ("L4  Gateway (KMS)", "verify biometric signature + 60 s TTL on /confirm", AMBER),
        ("L5  Execute", "DBS payment API \u2192 EXECUTION_COMPLETE, trail hashed", TEAL),
    ]
    y = 1500000
    for name, desc, col in layers:
        box(s, 630000, y, 10800000, 560000, fill=LIGHT)
        chip(s, 830000, y + 80000, name, fill=col, size=12)
        text(s, 2500000, y + 120000, 8800000, 340000, desc, size=13, color=PALE)
        y += 650000
    footer(s)

    # Slide 5 — response types
    s = add_slide(prs)
    bg(s, NAVY)
    header(s, "04", "Six response types", "The complete state space of one /intent turn")
    rows = [
        ("draft", "ready for biometric confirmation — all layers passed", GREEN),
        ("clarify", "one more answer needed (payee / amount / account)", TEAL),
        ("frozen", "discrepancy — held for manual review", AMBER),
        ("blocked", "refused before any model call (shield hit)", RED),
        ("chat", "no transaction found — hard boundary away from the gateway", TEAL),
        ("error", "unrecoverable pipeline failure", RED),
    ]
    y = 1500000
    for name, desc, col in rows:
        box(s, 630000, y, 10800000, 700000, fill=LIGHT)
        text(s, 930000, y + 120000, 1800000, 400000, name, size=17, bold=True, color=col)
        text(s, 3100000, y + 140000, 8000000, 380000, desc, size=13, color=PALE)
        y += 790000
    footer(s)

    # Slide 6 — section tencent services
    section_slide(prs, "05", "Tencent Cloud integration",
                  "Six Tencent services, each with one job",
                  ["ADP — Agent Development Platform: intent parsing (Layer 2), AppKey auth, SSE, v2 international",
                   "TRTC ASR v3 — voice \u2192 text with UserSig auth; no separate service activation",
                   "TTS (TextToVoice) — clarification & confirmation spoken back (backend ready)",
                   "KMS — VerifyByAsymmetricKey for the biometric gateway (the one real crypto boundary)",
                   "COS — raw-audio archive for the audit trail",
                   "TDSQL-C / PostgreSQL — append-only audit chain + payee registry storage"])

    # Slide 7 — services table
    s = add_slide(prs)
    bg(s, NAVY)
    header(s, "06", "Service map", "What it does in this pipeline, credential, and honest status")
    cols = [(630000, 2500000, "Service"), (3400000, 4300000, "Job in the pipeline"),
            (7800000, 1900000, "Credential"), (9800000, 1700000, "Status")]
    for x, w, c in cols:
        text(s, x, 1500000, w, 300000, c, size=13, bold=True, color=TEAL)
    rows = [
        ("ADP", "parse utterance \u2192 Intent[] (Layer 2)", "ADP_APP_KEY", "working \u00b7 5\u20139 s"),
        ("TRTC ASR v3", "voice \u2192 transcript (Scenario 1)", "AppID + UserSig", "auth ok \u00b7 speech unverified"),
        ("TTS", "text \u2192 MP3 for prompts", "SecretId/Key", "backend ok \u00b7 no UI caller"),
        ("KMS", "verify biometric signature on /confirm", "CAM + KMS_KEY_ID", "configured \u00b7 untested"),
        ("COS", "archive raw audio for audit", "SecretId/Key", "configured \u00b7 never called"),
        ("PostgreSQL", "audit chain + payees table", "DATABASE_URL", "working"),
    ]
    y = 1900000
    for name, job, cred, status in rows:
        box(s, 630000, y, 10800000, 660000, fill=LIGHT)
        text(s, 830000, y + 140000, 2300000, 400000, name, size=14, bold=True, color=TEAL)
        text(s, 3400000, y + 140000, 4200000, 400000, job, size=12, color=PALE)
        text(s, 7800000, y + 140000, 1800000, 400000, cred, size=11, color=GREY)
        text(s, 9750000, y + 140000, 1650000, 400000, status, size=11, color=AMBER if status not in ("working",) else GREEN)
        y += 735000
    footer(s)

    # Slide 8 — ADP endpoint trap
    s = add_slide(prs)
    bg(s, NAVY)
    header(s, "07", "The ADP endpoint trap", "A key mismatch returns the identical 4505004 error \u2014 as HTTP 200")
    box(s, 630000, 1500000, 10800000, 900000, fill=AMBER)
    text(s, 930000, 1600000, 10300000, 700000,
         "Host and field names must agree. Every mismatch \u2014 wrong host, wrong schema, bad key \u2014 "
         "returns code 4505004 \u201cAPPKEY is invalid\u201d delivered as an SSE error inside an HTTP 200. "
         "Status codes never reveal the cause; the discriminating test is calling both hosts.",
         size=15, color=NAVY, bold=False)
    rows = [
        ("International", "wss.lke.tencentcloud.com/adp/v2/chat", "AppKey", "\u2705 used"),
        ("International (fallback)", "wss.lke.tencentcloud.com/v1/qbot/chat/sse", "bot_app_key", "sunset 2026-12-31"),
        ("China", "wss.lke.cloud.tencent.com/adp/v2/chat", "AppKey", "not used"),
        ("China (fallback)", "wss.lke.cloud.tencent.com/v1/qbot/chat/sse", "bot_app_key", "not used"),
    ]
    y = 2800000
    for console, ep, auth, state in rows:
        box(s, 630000, y, 10800000, 640000, fill=LIGHT)
        text(s, 830000, y + 150000, 2200000, 350000, console, size=13, bold=True, color=WHITE)
        text(s, 3300000, y + 150000, 5200000, 350000, ep, size=12, color=PALE)
        text(s, 8800000, y + 150000, 1400000, 350000, auth, size=12, color=GREY)
        text(s, 10400000, y + 150000, 900000, 350000, state, size=12, color=GREEN if state.startswith("\u2705") else GREY)
        y += 700000
    footer(s)

    # Slide 9 — the request path
    s = add_slide(prs)
    bg(s, NAVY)
    header(s, "08", "The request path, end to end", "One /intent call walks seven gates before a draft is confirmable")
    steps = [
        ("0  Audit", "INPUT_RECEIVED logged, hash-chained"),
        ("2  ADP parser", "utterance \u2192 Intent[]"),
        ("2a No-intent?", "empty \u2192 chat"),
        ("1  Shield", "injection \u2192 blocked"),
        ("2b Backfill", "registry-authoritative identity"),
        ("2c Ambiguity?", "open question \u2192 clarify"),
        ("3  Validator", "discrepancy \u2192 frozen"),
        ("4  Draft \u2192 /confirm", "KMS verify \u2192 execute \u2192 auditHash"),
    ]
    y = 1500000
    for step, desc in steps:
        box(s, 630000, y, 10800000, 600000, fill=LIGHT)
        box(s, 630000, y, 62000, 600000, fill=TEAL)
        text(s, 1000000, y + 110000, 3400000, 380000, step, size=15, bold=True, color=WHITE)
        text(s, 4800000, y + 130000, 6800000, 350000, desc, size=13, color=PALE)
        y += 650000
    box(s, 630000, y, 10800000, 420000, fill=AMBER)
    text(s, 930000, y + 90000, 10300000, 280000,
         "honest note: the shield screens the raw transcript but runs after ADP (main.py:144 vs 162) \u2014 nothing is confirmed or paid",
         size=12, color=NAVY)
    footer(s)

    # Slide 10 — voice path
    s = add_slide(prs)
    bg(s, NAVY)
    header(s, "09", "Voice path (Scenario 1)", "Voice and text share one code path \u2014 ASR feeds /intent directly")
    flow = [("mic", "MediaRecorder WebM/Opus"), ("POST /api/asr", "TRTC ASR v3"), ("transcript", "rawTranscript"),
            ("/api/intent", "the seven gates"), ("response", "draft / clarify / chat")]
    x = 630000
    for i, (name, desc) in enumerate(flow):
        box(s, x, 2200000, 2150000, 1500000, fill=LIGHT)
        text(s, x + 160000, 2450000, 1900000, 400000, name, size=16, bold=True, color=TEAL, align=PP_ALIGN.CENTER)
        text(s, x + 160000, 2950000, 1900000, 500000, desc, size=11, color=PALE, align=PP_ALIGN.CENTER)
        if i < len(flow) - 1:
            text(s, x + 2150000, 2750000, 400000, 400000, "\u2192", size=22, bold=True, color=GREY)
        x += 2550000
    bullets(s, 630000, 4200000, 10800000, 1800000,
            [("Formats ok:", "WAV / PCM / OGG-Opus / WebM; MP3 rejected (code=5000)"),
             ("Real-speech quality:", "still unverified \u2014 only a synthetic WAV was transcribed (empty transcript, no error)"),
             ("App is voice-in / text-out:", "/tts works on the backend but the UI never calls it"),
             ("Signing:", "frontend uses toySign in page context \u2014 a stand-in, not WebAuthn")],
            size=14, gap=12)
    footer(s)

    # Slides 10-13 — live demo, one full-width screenshot each
    demo = [
        ("10", "Live demo — multi-intent",
         "\u201cTransfer $500 to mom + invest the rest in Apple\u201d  \u2192  TRANSFER $500.00 + INVEST $4,320.50 = SGD 4,820.50",
         "demo_multintent.jpg"),
        ("11", "Live demo — ambiguous payee",
         "\u201cSend fifty to John\u201d  \u2192  clarify John Tan / John Lim  \u2192  draft $50.00  \u2192  confirmed",
         "demo_clarify.jpg"),
        ("12", "Live demo — prompt-injection blocked",
         "\u201cignore all previous instructions\u201d  \u2192  Potential prompt injection detected. Request blocked",
         "demo_blocked.jpg"),
        ("13", "Live demo — the audit trail",
         "INPUT_RECEIVED \u2192 PARSER_OUTPUT \u2192 VALIDATION_PASS \u2192 GATEWAY_ACCEPT \u2192 EXECUTION_COMPLETE",
         "demo_audit.jpg"),
    ]
    for num, title, sub, fn in demo:
        s = add_slide(prs)
        bg(s, NAVY)
        header(s, num, title, sub)
        photo(s, str(FRAMES / fn), 600000, 990000, 10992000, 5420000)
        footer(s, "Screenshot from DBS_Payment.mp4 \u2014 deployed instance https://43.153.195.85")

    # Verification section
    section_slide(prs, "14", "Verification",
                  "What is actually true about this build",
                  ["Backend suite: 76 passed, 1 skipped (the skip is credential-dependent ASR 503)",
                   "Live acceptance through nginx: blocked / frozen / draft / clarify all reproduced",
                   "Non-transaction input: 9/9 \u2192 chat, draft: null, no 500",
                   "Eval set (Eval/DCTA Eval Set 1002.xlsx): 32 cases \u00d7 9 sessions, auto-run 32/32 with --delay 3",
                   "ADP throttles bursts \u2014 sustained rapid calls degrade to empty intents",
                   "76 tests + 32 live eval calls cover transfers, investments, ambiguity, injection, chitchat, voice markers, and the full clarify \u2192 resolve \u2192 confirm handoff"])

    # Slide 12 — eval stats
    s = add_slide(prs)
    bg(s, NAVY)
    header(s, "15", "Eval & coverage", "R1\u2013R7 handbook requirements, exercised live")
    stat_card(s, 630000, 1650000, 3400000, "76", "backend tests passing", TEAL)
    stat_card(s, 4270000, 1650000, 3400000, "32", "live eval cases (9 sessions)", GREEN)
    stat_card(s, 7910000, 1650000, 3400000, "32/32", "eval pass rate (delayed runs)", GREEN)
    bullets(s, 630000, 3200000, 10800000, 2800000,
            [("Zero-UI multi-intent parsing", "\u2014 transfers, investments, relative amounts \u2192 R1"),
             ("Dynamic ambiguity resolution", "\u2014 payee/amount/account clarify \u2192 R2"),
             ("Dual-engine semantic validation", "\u2014 rule re-derivation freezes discrepancies \u2192 R3"),
             ("Deterministic HITL biometric auth", "\u2014 /confirm gateway \u2192 R4/R5"),
             ("Adversarial shield", "\u2014 injection blocked on raw text \u2192 R6"),
             ("Fully traceable audit ledger", "\u2014 hash-chained events in Postgres \u2192 R8")],
            size=15, gap=11)
    footer(s)

    # Slide 13 — honest gaps
    s = add_slide(prs)
    bg(s, NAVY)
    header(s, "16", "Known gaps (not silently fixed)", "Ranked from review.md \u2014 the deck stays honest")
    gaps = [
        ("Signing is toySign in page context", "not a secure enclave / WebAuthn; agent and gateway share one process"),
        ("No velocity throttling", "HIGH_VALUE_THRESHOLD freezes big transfers, but no rate counter for many small ones"),
        ("No nonce", "a captured signed envelope is replayable inside the 60 s TTL"),
        ("Audio never archived", "archive_audio_to_cos is defined but never called"),
        ("KMS & COS configured but untested", "the demo runs the deterministic toy path"),
        ("/confirm does not re-read balances", "a relative amount executes from a stale number"),
        ("Credentials were exposed during dev", "ADP AppKey, TRTC SDKSecretKey, CAM keys \u2014 all need rotating"),
        ("payees table unread", "parser still resolves from static accounts.py, not Postgres"),
    ]
    y = 1500000
    for i, (name, desc) in enumerate(gaps):
        col = LIGHT
        box(s, 630000, y, 10800000, 560000, fill=col)
        text(s, 930000, y + 90000, 5600000, 350000, name, size=14, bold=True, color=AMBER)
        text(s, 6700000, y + 90000, 4800000, 350000, desc, size=12, color=PALE)
        y += 600000
    footer(s)

    # Slide 14 — takeaways
    s = add_slide(prs)
    bg(s, NAVY)
    header(s, "17", "Takeaways", "What this build demonstrates")
    bullets(s, 630000, 1650000, 10800000, 3600000,
            ["A trustworthy conversational transaction agent is an architecture problem, not a model problem",
             "The five layers convert an LLM\u2019s proposal into a signed, auditable instruction \u2014 every layer is code, not prompt",
             "Tencent Cloud supplies the whole platform: ADP for parsing, TRTC for voice, TTS for speech out, KMS for the gateway, COS for evidence, TDSQL-C for the ledger",
             "Fast and honest iteration: 73 \u2192 76 tests, 9/9 chitchat fixed, 32/32 live eval, and the remaining gaps are listed, not hidden"],
            size=17, gap=16)
    box(s, 630000, 5600000, 10800000, 760000, fill=TEAL)
    text(s, 930000, 5750000, 10400000, 450000,
         "Dex from DBS · Tencent Cloud AI CAN DO IT Hackathon · code in dcta_tentcent",
         size=16, bold=True, color=NAVY)
    footer(s)

    prs.save(path)
    print(f"wrote {path}: {len(prs.slides.__iter__.__self__._sldIdLst)} slides")


if __name__ == "__main__":
    from pathlib import Path
    out = Path(__file__).resolve().parent.parent / "Deck" / "DBS-DCTA-Deck.pptx"
    out.parent.mkdir(exist_ok=True)
    build(str(out))