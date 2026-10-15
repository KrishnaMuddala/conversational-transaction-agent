"""
Adversarial / safety shield.
On Tencent Cloud this should be supplemented by WAF and content moderation APIs.
"""

import re

from services.accounts import KNOWN_PAYEES, KNOWN_ACCOUNTS


INJECTION_PATTERNS = [
    "ignore all previous instructions",
    "ignore previous instructions",
    "you are now",
    "disregard",
    "system prompt",
    "new instruction",
    "do not tell anyone",
    "ignore the above",
]

# A bare run of 5+ digits is far more often a transaction amount than an account
# number, so money is excluded before the account-number check runs.
_CURRENCY_BEFORE = re.compile(r"(?:s?gd|usd|eur|gbp|sg\$|us\$|\$|€|£)\s*$", re.IGNORECASE)
_CURRENCY_AFTER = re.compile(r"^\s*(?:dollars?|bucks?|cents?|sgd|usd|eur|gbp|euros?|pounds?)", re.IGNORECASE)
_ACCOUNT_CONTEXT = re.compile(r"(?:account|acct|a/c|beneficiary)\b", re.IGNORECASE)
_DIGIT_RUN = re.compile(r"\b\d{4,}[-]?\d+\b")


def _is_money(raw: str, match: re.Match) -> bool:
    """True when the digit run is a monetary amount rather than an account id."""
    before = raw[: match.start()]
    after = raw[match.end():]
    if _CURRENCY_BEFORE.search(before):
        return True
    if _CURRENCY_AFTER.match(after):
        return True
    return False


def _mentions_account(raw: str, match: re.Match) -> bool:
    """True when the digit run is described as an account identifier."""
    window = raw[max(0, match.start() - 40): match.end() + 40]
    if _ACCOUNT_CONTEXT.search(window):
        return True
    # Hyphenated form (1234-5678) is an account-number convention.
    return "-" in match.group(0)


def run_safety_checks(raw: str) -> dict:
    lower = raw.lower()

    for pattern in INJECTION_PATTERNS:
        if pattern in lower:
            return {
                "ok": False,
                "reason": f'Potential prompt injection detected: "{pattern}". Request blocked.'
            }

    # Detect raw account numbers that are not known payees or accounts.
    known_ids = [p.account for group in KNOWN_PAYEES.values() for p in group if p.account]
    known_account_ids = [a.id for a in KNOWN_ACCOUNTS.values()]

    for match in _DIGIT_RUN.finditer(raw):
        if _is_money(raw, match) or not _mentions_account(raw, match):
            continue

        acct = match.group(0)
        if not any(acct in known_id for known_id in known_ids) and acct not in known_account_ids:
            return {
                "ok": False,
                "reason": f'Unregistered account number "{acct}" detected. Request blocked.'
            }

    return {"ok": True}
