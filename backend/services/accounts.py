"""
Static account / payee / asset data for the prototype.
In production these should come from the DBS customer profile API
or a Tencent Cloud database.
"""

from models import Account, Payee, Asset


KNOWN_ACCOUNTS: dict[str, Account] = {
    "savings": Account(id="acc_savings", type="Savings", balance=4820.50, currency="SGD"),
    "current": Account(id="acc_current", type="Current", balance=1250.00, currency="SGD"),
    "cpf": Account(id="acc_cpf", type="CPF Investment", balance=150000.00, currency="SGD"),
}


KNOWN_PAYEES: dict[str, list[Payee]] = {
    "john": [
        Payee(id="payee_john_tan", name="John Tan", bank="DBS", account="***9921"),
        Payee(id="payee_john_lim", name="John Lim", bank="OCBC", account="***7734"),
    ],
    "mary": [Payee(id="payee_mary", name="Mary Ong", bank="DBS", account="***1140")],
    "mom": [Payee(id="payee_mom", name="Mom", bank="DBS", account="***2201")],
}


KNOWN_ASSETS: dict[str, Asset] = {
    "apple": Asset(symbol="AAPL", name="Apple Inc."),
    "nvidia": Asset(symbol="NVDA", name="NVIDIA Corp."),
    "tesla": Asset(symbol="TSLA", name="Tesla Inc."),
    "dbs": Asset(symbol="D05", name="DBS Group Holdings"),
}


def get_account(name: str | None) -> Account:
    if not name:
        return KNOWN_ACCOUNTS["savings"]
    return KNOWN_ACCOUNTS.get(name.lower(), KNOWN_ACCOUNTS["savings"])


def resolve_payee(name: str | None) -> dict:
    if not name:
        return {"selected": None, "candidates": [], "confidence": 0.3, "name": name}
    key = name.lower()
    if key in KNOWN_PAYEES:
        candidates = KNOWN_PAYEES[key]
        if len(candidates) == 1:
            return {"selected": candidates[0], "candidates": candidates, "confidence": 0.95, "name": name}
        return {"selected": None, "candidates": candidates, "confidence": 0.5, "name": name}
    return {"selected": None, "candidates": [], "confidence": 0.3, "name": name}


def resolve_asset(name: str | None, symbol: str | None = None) -> dict:
    for key, asset in KNOWN_ASSETS.items():
        if name and key in name.lower():
            return {"selected": asset, "candidates": [asset], "confidence": 0.95, "name": asset.name}
        if symbol and asset.symbol.lower() == symbol.lower():
            return {"selected": asset, "candidates": [asset], "confidence": 0.95, "name": asset.name}
    return {"selected": None, "candidates": [], "confidence": 0.3, "name": None}


def resolve_account_destination(name: str | None) -> dict:
    """If the destination is another known account, return it as a payee-like object."""
    if not name:
        return {"selected": None, "candidates": [], "confidence": 0.2, "name": None}
    clean = name.lower().replace(" account", "").replace(" acc", "").strip()
    if clean in KNOWN_ACCOUNTS:
        acc = KNOWN_ACCOUNTS[clean]
        obj = {
            "id": acc.id,
            "name": f"{acc.type} Account",
            "bank": "DBS",
            "account": acc.id,
        }
        return {"selected": obj, "candidates": [obj], "confidence": 0.95, "name": obj["name"]}
    return {"selected": None, "candidates": [], "confidence": 0.2, "name": name}
