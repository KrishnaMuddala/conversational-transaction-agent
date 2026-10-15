"""
Payee directory — read-through cache of a DBS-sourced payee list.

Status: STORAGE ONLY. Nothing in the running application reads this table yet.
The parser still resolves payees from the hardcoded KNOWN_PAYEES dict in
`accounts.py`, so the application is unaffected by anything here. That is
deliberate — see DESIGN_PAYEE_DIRECTORY.md §7 (sequencing).

    127.0.0.1:5432  psql -U postgres -d dbs_dcta
    SELECT id, name, bank, account_masked, status FROM payees ORDER BY name;

Why the schema looks like this (DESIGN_PAYEE_DIRECTORY.md §4):

  * `account_masked` is named for what it is. A raw account number must never be
    written to this column. In a real integration this row would hold the payee
    token / mandate id that DBS issued, and the masked form is derived for
    display. The seed below has no raw numbers because none exist yet.
  * `effective_from` / `effective_to` instead of in-place updates, so any
    resolution is traceable to the directory as it stood at that moment.
  * `status` gives revocation instead of deletion. A revoked payee must stop
    resolving immediately, and a hard DELETE destroys the dispute trail.
  * `source_system` / `last_synced_at` record provenance, since this table is a
    cache of something DBS owns, not a system of record.

Usage:

    python -m services.payee_store --init
    python -m services.payee_store --init --database-url postgresql://postgres:postgres@127.0.0.1:5432/dbs_dcta

`--init` is idempotent: it creates the table if absent and upserts by `id`.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from typing import Any

from sqlalchemy import (
    BigInteger,
    String,
    create_engine,
    text,
)
from sqlalchemy.orm import Mapped, declarative_base, mapped_column

from models import Payee


Base = declarative_base()


class PayeeORM(Base):
    __tablename__ = "payees"

    # Canonical identifier, matches Payee.id in models.py.
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # Lookup key currently used by accounts.resolve_payee() ("john", "mary",
    # "mom"). Carried here so a future DB-backed resolver can reproduce the
    # existing ambiguous-group behaviour exactly.
    match_key: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    bank: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Masked display form only. Never a raw account number.
    account_masked: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Lifecycle
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    effective_from: Mapped[int] = mapped_column(BigInteger)
    effective_to: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # Provenance — this table is a cache, not the system of record
    source_system: Mapped[str] = mapped_column(String(64), default="dbs")
    last_synced_at: Mapped[int] = mapped_column(BigInteger)

    created_at: Mapped[int] = mapped_column(BigInteger)


# Mirrors KNOWN_PAYEES in services/accounts.py. Deliberately a copy: the app does
# not read this yet, and when it is switched over, accounts.py should be deleted
# rather than left to drift. Kept literal so the two can be diffed by eye.
SEED_PAYEES: list[dict[str, str | None]] = [
    {"id": "payee_john_tan", "match_key": "john", "name": "John Tan", "bank": "DBS", "account_masked": "***9921"},
    {"id": "payee_john_lim", "match_key": "john", "name": "John Lim", "bank": "OCBC", "account_masked": "***7734"},
    {"id": "payee_mary", "match_key": "mary", "name": "Mary Ong", "bank": "DBS", "account_masked": "***1140"},
    {"id": "payee_mom", "match_key": "mom", "name": "Mom", "bank": "DBS", "account_masked": "***2201"},
]


def _now() -> int:
    return int(dt.datetime.now(dt.timezone.utc).timestamp())


def _assert_matches_static_registry() -> None:
    """Fail loudly if the seed drifts from the dict the app actually uses.

    These two lists are meant to be the same data. If someone edits one and not
    the other, the directory and the running application would disagree about
    who a payee is — the exact shadow-record drift the design note warns about.
    """
    from services.accounts import KNOWN_PAYEES

    static = {
        p.id: (key, p.name, p.bank, p.account)
        for key, group in KNOWN_PAYEES.items()
        for p in group
    }
    seeded = {
        row["id"]: (row["match_key"], row["name"], row["bank"], row["account_masked"])
        for row in SEED_PAYEES
    }
    if static != seeded:
        only_static = {k: v for k, v in static.items() if seeded.get(k) != v}
        only_seeded = {k: v for k, v in seeded.items() if static.get(k) != v}
        raise SystemExit(
            "payee seed has drifted from services/accounts.py KNOWN_PAYEES:\n"
            f"  only in accounts.py: {only_static}\n"
            f"  only in payee_store:  {only_seeded}\n"
            "Reconcile the two before seeding."
        )


def init_db(database_url: str, *, seed: bool = True, verify: bool = True) -> int:
    """Create the table if absent and upsert the seed. Idempotent."""
    if verify:
        _assert_matches_static_registry()

    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as conn:
            Base.metadata.create_all(conn)
            if not seed:
                return 0
            now = _now()
            for row in SEED_PAYEES:
                conn.execute(
                    text(
                        """
                        INSERT INTO payees
                            (id, match_key, name, bank, account_masked, status,
                             effective_from, effective_to, source_system,
                             last_synced_at, created_at)
                        VALUES
                            (:id, :match_key, :name, :bank, :account_masked, 'active',
                             :effective_from, NULL, 'seed', :now, :now)
                        ON CONFLICT (id) DO UPDATE SET
                            match_key      = EXCLUDED.match_key,
                            name           = EXCLUDED.name,
                            bank           = EXCLUDED.bank,
                            account_masked = EXCLUDED.account_masked,
                            status         = EXCLUDED.status,
                            effective_from = EXCLUDED.effective_from,
                            last_synced_at = EXCLUDED.last_synced_at
                        RETURNING (xmax = 0) AS inserted
                        """
                    ),
                    {
                        "id": row["id"],
                        "match_key": row["match_key"],
                        "name": row["name"],
                        "bank": row["bank"],
                        "account_masked": row["account_masked"],
                        "effective_from": now,
                        "now": now,
                    },
                )
        return len(SEED_PAYEES)
    finally:
        engine.dispose()


def count_rows(database_url: str) -> int:
    engine = create_engine(database_url, future=True)
    try:
        with engine.connect() as conn:
            return int(conn.execute(text("SELECT count(*) FROM payees")).scalar_one())
    finally:
        engine.dispose()


def _default_url() -> str:
    from config import get_settings

    return get_settings().DATABASE_URL


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create and seed the payee directory.")
    parser.add_argument("--init", action="store_true", help="create the table and upsert the seed")
    parser.add_argument(
        "--database-url",
        default=None,
        help=(
            "Postgres URL. Defaults to DATABASE_URL from the environment, which is "
            "written for the Docker network (host 'db') and will NOT resolve from "
            "the host laptop. Pass an explicit host URL to seed from the host, e.g. "
            "--database-url postgresql://postgres:postgres@127.0.0.1:5432/dbs_dcta"
        ),
    )
    parser.add_argument("--no-verify", action="store_true", help="skip the drift check against accounts.py")
    args = parser.parse_args(argv)

    url = args.database_url or _default_url()

    if not args.init:
        parser.print_help()
        print("\nnothing to do; pass --init")
        return 1

    written = init_db(url, verify=not args.no_verify)
    total = count_rows(url)
    print(f"payee table ready at {url.split('@')[-1]}")
    print(f"seeded {written} row(s); {total} row(s) total")
    print("note: the application still resolves payees from services/accounts.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
