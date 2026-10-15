"""
Immutable audit logger.

Production:
  - Writes structured events to TDSQL (PostgreSQL).
  - Archives raw audio and large payloads to COS.

The previous hash field creates a simple tamper-evident chain.
"""

from __future__ import annotations

import base64
import json
from typing import Any
from contextvars import ContextVar

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base, Mapped, mapped_column
from sqlalchemy import select, desc, BigInteger

from config import get_settings
from models import AuditEvent


Base = declarative_base()


class AuditEventORM(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ts: Mapped[int] = mapped_column(BigInteger, index=True)
    turn_id: Mapped[str] = mapped_column(index=True)
    event: Mapped[str]
    payload: Mapped[str | None]
    previous_hash: Mapped[str | None]


current_session: ContextVar[AsyncSession | None] = ContextVar("current_session", default=None)


class AuditLogger:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.engine = None
        self.SessionLocal = None
        self.memory: list[dict] = []
        self.memory_mode = False

    async def init_db(self, attempts: int = 10, delay: float = 1.5):
        if self.engine or self.memory_mode:
            return

        url = self.settings.DATABASE_URL
        if url.startswith("postgresql://") and "asyncpg" not in url:
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)

        import asyncio
        import logging

        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            engine = create_async_engine(url, echo=False)
            try:
                async with engine.begin() as conn:
                    await conn.run_sync(Base.metadata.create_all)
                self.engine = engine
                self.SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
                logging.info(f"Audit logger connected to database (attempt {attempt}).")
                return
            except Exception as e:
                last_error = e
                await engine.dispose()
                if attempt < attempts:
                    logging.warning(
                        f"Database unavailable (attempt {attempt}/{attempts}: {e}); retrying in {delay}s."
                    )
                    await asyncio.sleep(delay)

        logging.warning(
            f"Database unavailable after {attempts} attempts ({last_error}); "
            "falling back to in-memory audit logger."
        )
        self.memory_mode = True

    async def close(self):
        if self.engine:
            await self.engine.dispose()

    async def append(self, event: AuditEvent):
        if self.memory_mode:
            self.memory.append({
                "ts": event.ts,
                "turn_id": event.turnId,
                "event": event.event,
                "payload": event.payload,
            })
            return

        if self.SessionLocal is None:
            await self.init_db()
            if self.memory_mode:
                return await self.append(event)

        payload_json = json.dumps(event.payload, default=str) if event.payload is not None else None
        previous_hash = await self._previous_hash()

        async with self.SessionLocal() as session:
            async with session.begin():
                orm_event = AuditEventORM(
                    ts=event.ts,
                    turn_id=event.turnId,
                    event=event.event,
                    payload=payload_json,
                    previous_hash=previous_hash,
                )
                session.add(orm_event)

    async def get(self, turn_id: str | None = None, limit: int = 100) -> list[AuditEvent]:
        if self.memory_mode:
            rows = [r for r in self.memory if turn_id is None or r["turn_id"] == turn_id]
            rows = rows[-limit:]
            return [AuditEvent(ts=r["ts"], turnId=r["turn_id"], event=r["event"], payload=r["payload"]) for r in rows]

        if self.SessionLocal is None:
            await self.init_db()
            if self.memory_mode:
                return await self.get(turn_id, limit)

        async with self.SessionLocal() as session:
            stmt = select(AuditEventORM).order_by(desc(AuditEventORM.id))
            if turn_id:
                stmt = stmt.where(AuditEventORM.turn_id == turn_id)
            stmt = stmt.limit(limit)
            result = await session.execute(stmt)
            rows = result.scalars().all()
            return [
                AuditEvent(
                    ts=row.ts,
                    turnId=row.turn_id,
                    event=row.event,
                    payload=json.loads(row.payload) if row.payload else None,
                )
                for row in rows
            ]

    async def get_by_turn(self, turn_id: str) -> list[AuditEvent]:
        return await self.get(turn_id=turn_id, limit=1000)

    async def _previous_hash(self) -> str:
        if self.memory_mode:
            if not self.memory:
                return "0" * 64
            last = self.memory[-1]
            data = f"{last['ts']}|{last['turn_id']}|{last['event']}|{last['payload']}|{last.get('previous_hash', '0'*64)}"
            return hash_chain(data)

        if self.SessionLocal is None:
            await self.init_db()
            if self.memory_mode:
                return await self._previous_hash()

        async with self.SessionLocal() as session:
            stmt = select(AuditEventORM).order_by(desc(AuditEventORM.id)).limit(1)
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if not row:
                return "0" * 64
            data = f"{row.ts}|{row.turn_id}|{row.event}|{row.payload}|{row.previous_hash}"
        return hash_chain(data)

    async def archive_audio_to_cos(self, turn_id: str, audio_bytes: bytes) -> str:
        """Upload raw audio to COS and return object URL."""
        try:
            from qcloud_cos import CosConfig, CosS3Client
        except ImportError:
            return ""

        settings = self.settings
        if not settings.COS_BUCKET:
            return ""

        config = CosConfig(
            Region=settings.COS_REGION,
            SecretId=settings.COS_SECRET_ID,
            SecretKey=settings.COS_SECRET_KEY,
        )
        client = CosS3Client(config)
        key = f"audio/{turn_id}.mp3"
        client.put_object(
            Bucket=settings.COS_BUCKET,
            Body=audio_bytes,
            Key=key,
        )
        return f"https://{settings.COS_BUCKET}.cos.{settings.COS_REGION}.myqcloud.com/{key}"


def hash_chain(data: str) -> str:
    import hashlib
    return hashlib.sha256(data.encode()).hexdigest()


# Singleton
_audit_logger: AuditLogger | None = None


def get_audit_logger() -> AuditLogger:
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger()
    return _audit_logger
