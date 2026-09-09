"""Persistent deterministic synthetic customer backend.

The sandbox stores ordinary world state, never conversational intent.  Fixtures
remain responsible only for deterministic latency/failure injection and test oracles.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

DEMO_CUSTOMER_ID = "DEMO-1001"

_SEED: dict[str, list[tuple[str, str, dict[str, Any]]]] = {
    "restaurant": [
        (
            "reservation",
            "RES-801",
            {
                "reservation_id": "RES-801",
                "customer": "Demo Customer",
                "restaurant": "Demo Bistro",
                "date": "2026-09-12",
                "time": "8:00 PM",
                "party_size": 4,
                "status": "CONFIRMED",
                "partner_status": "FOUND",
            },
        ),
    ],
    "salon": [
        (
            "appointment",
            "APT-401",
            {
                "appointment_id": "APT-401",
                "customer": "Demo Customer",
                "salon": "Demo Studio",
                "service": "Haircut",
                "provider": "Asha",
                "date": "2026-09-15",
                "time": "4:00 PM",
                "status": "CONFIRMED",
                "change_cause": "NONE",
            },
        ),
    ],
    "hotel": [
        (
            "booking",
            "HTL-201",
            {
                "booking_id": "HTL-201",
                "guest": "Demo Customer",
                "hotel": "Demo Grand",
                "check_in": "2026-09-20",
                "check_out": "2026-09-22",
                "room_type": "Deluxe King",
                "guest_count": 2,
                "status": "CONFIRMED",
                "partner_status": "FOUND",
            },
        ),
    ],
    "ecommerce": [
        (
            "order",
            "ORD-301",
            {
                "order_id": "ORD-301",
                "item": "Wireless headphones",
                "status": "DELIVERED",
                "payment_status": "PAID",
                "return_status": "NONE",
            },
        ),
        (
            "refund",
            "REF-301",
            {
                "refund_id": "REF-301",
                "order_id": "ORD-301",
                "amount": "₹2,499",
                "processing_status": "PROCESSED",
                "settlement_status": "PENDING",
            },
        ),
    ],
    "banking": [
        (
            "card",
            "CARD-101",
            {
                "card_id": "CARD-101",
                "last4": "4821",
                "status": "ACTIVE",
                "online_transactions": "ENABLED",
                "registered_mobile_status": "VERIFIED",
            },
        ),
        (
            "transaction",
            "TXN-501",
            {
                "transaction_id": "TXN-501",
                "merchant": "Demo Merchant",
                "amount": "₹1,250",
                "status": "DECLINED",
            },
        ),
        (
            "otp",
            "OTP-601",
            {
                "otp_event_id": "OTP-601",
                "transaction_id": "TXN-501",
                "generation_status": "SUCCESS",
                "delivery_status": "FAILED",
                "failure_reason": "SMS_PROVIDER_FAILURE",
            },
        ),
        (
            "service",
            "SMS-STATUS",
            {
                "service_id": "SMS-STATUS",
                "service": "sms_provider",
                "status": "DEGRADED",
                "summary": "Synthetic SMS delivery degradation",
            },
        ),
    ],
}

_AVAILABILITY = [
    ("restaurant", "Demo Bistro", "2026-09-12", "7:00 PM", 1),
    ("restaurant", "Demo Bistro", "2026-09-12", "8:00 PM", 1),
    ("salon", "Demo Studio", "2026-09-15", "3:00 PM", 1),
    ("salon", "Demo Studio", "2026-09-15", "4:00 PM", 1),
]


class SyntheticSupportSandbox:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._init_schema()
        if not self.lookup_customer(DEMO_CUSTOMER_ID):
            self.reset_demo_data()

    def _init_schema(self) -> None:
        with self._db:
            self._db.executescript("""
                CREATE TABLE IF NOT EXISTS customers (
                    customer_id TEXT PRIMARY KEY, display_name TEXT NOT NULL, synthetic INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS records (
                    domain TEXT NOT NULL, record_type TEXT NOT NULL, record_id TEXT NOT NULL,
                    customer_id TEXT NOT NULL, data_json TEXT NOT NULL, updated_at REAL NOT NULL,
                    PRIMARY KEY(domain, record_type, record_id)
                );
                CREATE TABLE IF NOT EXISTS availability (
                    domain TEXT NOT NULL, resource TEXT NOT NULL, date TEXT NOT NULL,
                    time TEXT NOT NULL, available INTEGER NOT NULL,
                    PRIMARY KEY(domain, resource, date, time)
                );
                CREATE TABLE IF NOT EXISTS changes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, domain TEXT NOT NULL,
                    record_type TEXT NOT NULL, record_id TEXT NOT NULL, action TEXT NOT NULL,
                    before_json TEXT, after_json TEXT, created_at REAL NOT NULL
                );
            """)

    def reset_demo_data(self) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM changes")
            self._db.execute("DELETE FROM availability")
            self._db.execute("DELETE FROM records")
            self._db.execute("DELETE FROM customers")
            self._db.execute(
                "INSERT INTO customers VALUES (?, ?, 1)", (DEMO_CUSTOMER_ID, "Demo Customer")
            )
            now = time.time()
            for domain, records in _SEED.items():
                for record_type, record_id, data in records:
                    self._db.execute(
                        "INSERT INTO records VALUES (?, ?, ?, ?, ?, ?)",
                        (domain, record_type, record_id, DEMO_CUSTOMER_ID, json.dumps(data), now),
                    )
            self._db.executemany("INSERT INTO availability VALUES (?, ?, ?, ?, ?)", _AVAILABILITY)

    def lookup_customer(self, customer_id: str) -> dict[str, Any] | None:
        row = self._db.execute(
            "SELECT * FROM customers WHERE customer_id=?", (customer_id,)
        ).fetchone()
        return dict(row) if row else None

    def resolve_synthetic_identity(self, identifier: str) -> dict[str, Any] | None:
        """Resolve DEMO-1001 or a fake reservation/account record identifier."""
        direct = self.lookup_customer(identifier.upper())
        if direct:
            return direct
        needle = identifier.upper()
        rows = self._db.execute("SELECT customer_id, data_json FROM records").fetchall()
        for row in rows:
            if needle in {str(value).upper() for value in json.loads(row["data_json"]).values()}:
                return self.lookup_customer(row["customer_id"])
        return None

    def list_records(
        self, customer_id: str, domain: str, record_type: str | None = None
    ) -> list[dict[str, Any]]:
        sql = "SELECT data_json FROM records WHERE customer_id=? AND domain=?"
        args: list[Any] = [customer_id, domain]
        if record_type:
            sql += " AND record_type=?"
            args.append(record_type)
        return [json.loads(row["data_json"]) for row in self._db.execute(sql, args).fetchall()]

    def get_record(
        self, customer_id: str, domain: str, record_type: str, record_id: str | None = None
    ) -> dict[str, Any] | None:
        if record_id:
            row = self._db.execute(
                "SELECT data_json FROM records WHERE customer_id=? AND domain=? AND record_type=? AND record_id=?",
                (customer_id, domain, record_type, record_id),
            ).fetchone()
        else:
            row = self._db.execute(
                "SELECT data_json FROM records WHERE customer_id=? AND domain=? AND record_type=? ORDER BY updated_at DESC LIMIT 1",
                (customer_id, domain, record_type),
            ).fetchone()
        return json.loads(row["data_json"]) if row else None

    def get_record_by_identifier(
        self,
        customer_id: str,
        domain: str,
        record_type: str,
        identifier: str,
    ) -> dict[str, Any] | None:
        """Resolve a record from a full, numeric, or voice-transcribed synthetic ID."""
        raw = str(identifier).strip().lower()
        words = {
            "zero": "0",
            "oh": "0",
            "one": "1",
            "two": "2",
            "three": "3",
            "four": "4",
            "five": "5",
            "six": "6",
            "seven": "7",
            "eight": "8",
            "nine": "9",
        }
        spoken_digits = "".join(
            words[token] for token in re.findall(r"[a-z]+", raw) if token in words
        )
        numeric = "".join(re.findall(r"\d", raw)) or spoken_digits
        canonical = raw.upper()
        for record in self.list_records(customer_id, domain, record_type):
            record_id = str(
                record.get(f"{record_type}_id")
                or record.get("id")
                or record.get("otp_event_id")
                or ""
            ).upper()
            if record_id == canonical or (numeric and record_id.endswith(numeric)):
                return record
        return None

    def find_record(
        self, customer_id: str, domain: str, record_type: str, field: str, value: Any
    ) -> dict[str, Any] | None:
        for record in self.list_records(customer_id, domain, record_type):
            if record.get(field) == value:
                return record
        return None

    def update_record(
        self,
        customer_id: str,
        domain: str,
        record_type: str,
        changes: dict[str, Any],
        record_id: str | None = None,
        action: str = "UPDATE",
    ) -> dict[str, Any]:
        with self._lock, self._db:
            current = self.get_record(customer_id, domain, record_type, record_id)
            if current is None:
                raise KeyError(f"No {domain} {record_type} record")
            key = record_id or str(current.get(f"{record_type}_id") or current.get("id"))
            updated = {**current, **{k: v for k, v in changes.items() if v is not None}}
            self._db.execute(
                "UPDATE records SET data_json=?, updated_at=? WHERE domain=? AND record_type=? AND record_id=?",
                (json.dumps(updated), time.time(), domain, record_type, key),
            )
            self._db.execute(
                "INSERT INTO changes(domain,record_type,record_id,action,before_json,after_json,created_at) VALUES(?,?,?,?,?,?,?)",
                (
                    domain,
                    record_type,
                    key,
                    action,
                    json.dumps(current),
                    json.dumps(updated),
                    time.time(),
                ),
            )
            return updated

    def create_record(
        self, customer_id: str, domain: str, record_type: str, record_id: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO records VALUES (?, ?, ?, ?, ?, ?)",
                (domain, record_type, record_id, customer_id, json.dumps(data), time.time()),
            )
            self._db.execute(
                "INSERT INTO changes(domain,record_type,record_id,action,before_json,after_json,created_at) VALUES(?,?,?,?,?,?,?)",
                (domain, record_type, record_id, "CREATE", None, json.dumps(data), time.time()),
            )
        return data

    def check_availability(
        self, domain: str, resource: str, date: str, requested_time: str
    ) -> dict[str, Any]:
        row = self._db.execute(
            "SELECT available FROM availability WHERE domain=? AND resource=? AND date=? AND time=?",
            (domain, resource, date, requested_time),
        ).fetchone()
        return {
            "resource": resource,
            "date": date,
            "requested_time": requested_time,
            "availability": "AVAILABLE" if row and row["available"] else "UNAVAILABLE",
        }

    def recent_changes(self, domain: str, limit: int = 8) -> list[dict[str, Any]]:
        rows = self._db.execute(
            "SELECT * FROM changes WHERE domain=? ORDER BY id DESC LIMIT ?", (domain, limit)
        ).fetchall()
        out = []
        for row in rows:
            before = json.loads(row["before_json"]) if row["before_json"] else {}
            after = json.loads(row["after_json"]) if row["after_json"] else {}
            fields = [
                {"field": key, "before": before.get(key), "after": after.get(key)}
                for key in sorted(set(before) | set(after))
                if before.get(key) != after.get(key)
            ]
            out.append(
                {
                    "id": row["id"],
                    "record_type": row["record_type"],
                    "record_id": row["record_id"],
                    "action": row["action"],
                    "fields": fields,
                }
            )
        return out

    def snapshot(self, customer_id: str, domain: str) -> dict[str, Any]:
        return {
            "customer": self.lookup_customer(customer_id),
            "domain": domain,
            "records": self.list_records(customer_id, domain),
            "recent_changes": self.recent_changes(domain),
        }
