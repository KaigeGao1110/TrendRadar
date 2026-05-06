"""Local SQLite storage for SEC Form D filings and company profiles.

Replaces Supabase tables for local-only operation.
"""

import sqlite3
import json
import os
from datetime import datetime, timezone
from typing import Optional, List, Dict, Set

DB_PATH = "/home/kaige/Projects/TrendRadar/data/sec.db"


class SecLocalDB:
    """SQLite client for SEC filings and company profiles."""

    def __init__(self, path: str = DB_PATH):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self._init_tables()

    def _init_tables(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS sec_form_d_filings (
                accession_number TEXT PRIMARY KEY,
                entity_name TEXT,
                industry_group TEXT,
                total_offering_amount REAL,
                filing_date TEXT,
                signature_date TEXT,
                raw_data TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );
        """)

        # Migrate sec_company_profiles: create if not exists, then add new columns
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS sec_company_profiles (
                normalized_name TEXT PRIMARY KEY,
                entity_name TEXT,
                description TEXT,
                primary_sector TEXT,
                sub_sector TEXT,
                target_customer TEXT,
                business_model TEXT,
                main_product TEXT,
                website TEXT,
                accession_numbers TEXT DEFAULT '[]',
                enrichment_source TEXT,
                enrichment_quality TEXT,
                quality_reason TEXT,
                enriched_at TEXT
            );
        """)

        # Add new columns if they don't exist (migration for existing tables)
        new_columns = [
            ("primary_sector", "TEXT"),
            ("sub_sector", "TEXT"),
            ("target_customer", "TEXT"),
            ("business_model", "TEXT"),
            ("main_product", "TEXT"),
            ("quality_reason", "TEXT"),
        ]
        for col_name, col_type in new_columns:
            try:
                self.conn.execute(f"ALTER TABLE sec_company_profiles ADD COLUMN {col_name} {col_type}")
            except Exception:
                pass  # Column already exists

        self.conn.executescript("""
            CREATE INDEX IF NOT EXISTS idx_filings_entity ON sec_form_d_filings(entity_name);
            CREATE INDEX IF NOT EXISTS idx_filings_industry ON sec_form_d_filings(industry_group);
            CREATE INDEX IF NOT EXISTS idx_profiles_sector ON sec_company_profiles(primary_sector);
        """)
        self.conn.commit()

    # ---- filings ----

    def upsert_filing(self, filing: dict):
        """Insert or update a filing."""
        self.conn.execute("""
            INSERT OR REPLACE INTO sec_form_d_filings
            (accession_number, entity_name, industry_group, total_offering_amount, filing_date, signature_date, raw_data)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            filing.get("accession_number"),
            filing.get("entity_name"),
            filing.get("industry_group"),
            filing.get("total_offering_amount"),
            filing.get("filing_date"),
            filing.get("signature_date"),
            json.dumps(filing, default=str),
        ))
        self.conn.commit()

    def upsert_filings_bulk(self, filings: list[dict]):
        """Bulk upsert filings."""
        for f in filings:
            self.conn.execute("""
                INSERT OR REPLACE INTO sec_form_d_filings
                (accession_number, entity_name, industry_group, total_offering_amount, filing_date, signature_date, raw_data)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                f.get("accession_number"),
                f.get("entity_name"),
                f.get("industry_group"),
                f.get("total_offering_amount"),
                f.get("filing_date"),
                f.get("signature_date"),
                json.dumps(f, default=str),
            ))
        self.conn.commit()

    def get_all_filings(self) -> list[dict]:
        """Get all filings."""
        rows = self.conn.execute("SELECT * FROM sec_form_d_filings").fetchall()
        return [dict(r) for r in rows]

    def get_filings_count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM sec_form_d_filings").fetchone()[0]

    # ---- profiles ----

    def get_existing_normalized_names(self) -> set[str]:
        rows = self.conn.execute("SELECT normalized_name FROM sec_company_profiles").fetchall()
        return {r["normalized_name"] for r in rows}

    def upsert_profile(self, profile: dict):
        """Insert or update a company profile."""
        self.conn.execute("""
            INSERT OR REPLACE INTO sec_company_profiles
            (normalized_name, entity_name, description, primary_sector, sub_sector, target_customer, business_model, main_product, website, accession_numbers, enrichment_source, enrichment_quality, quality_reason, enriched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            profile.get("normalized_name"),
            profile.get("entity_name"),
            profile.get("description"),
            profile.get("primary_sector"),
            profile.get("sub_sector"),
            profile.get("target_customer"),
            profile.get("business_model"),
            profile.get("main_product"),
            profile.get("website"),
            json.dumps(profile.get("accession_numbers", [])),
            profile.get("enrichment_source"),
            profile.get("enrichment_quality"),
            profile.get("quality_reason"),
            profile.get("enriched_at"),
        ))
        self.conn.commit()

    def get_profile_by_name(self, normalized_name: str) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT * FROM sec_company_profiles WHERE normalized_name = ?", (normalized_name,)
        ).fetchone()
        return dict(row) if row else None

    def get_profiles_count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM sec_company_profiles").fetchone()[0]

    def get_sector_counts(self) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT primary_sector, COUNT(*) as cnt FROM sec_company_profiles WHERE primary_sector IS NOT NULL GROUP BY primary_sector ORDER BY cnt DESC"
        ).fetchall()
        return {r["primary_sector"]: r["cnt"] for r in rows}

    def close(self):
        self.conn.close()