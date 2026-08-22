"""Idempotent migration: add medical_notes.weight_kg / temperature_celsius.

Uses the app's existing config (same env-var-driven DB connection as
config.Config, no hardcoded credentials). Checks INFORMATION_SCHEMA.COLUMNS
first and only ALTERs whichever column is missing, so it's safe to run
repeatedly and never touches existing data.

Run once by hand on the live database, e.g. via the Azure App Service SSH
console:
    python scripts/migrate_vitals_columns.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text

from config import Config

_CHECK_COLUMNS_SQL = text("""
    SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = :db_name
      AND TABLE_NAME = 'medical_notes'
      AND COLUMN_NAME IN ('weight_kg', 'temperature_celsius')
""")

_ADD_WEIGHT_KG_SQL = text(
    "ALTER TABLE medical_notes ADD COLUMN weight_kg DECIMAL(5,2) NULL"
)

_ADD_TEMPERATURE_CELSIUS_SQL = text(
    "ALTER TABLE medical_notes ADD COLUMN temperature_celsius DECIMAL(4,1) NULL"
)


def main():
    engine = create_engine(Config.SQLALCHEMY_DATABASE_URI, **Config.SQLALCHEMY_ENGINE_OPTIONS)

    applied = []
    skipped = []

    with engine.begin() as conn:
        existing = {
            row[0] for row in
            conn.execute(_CHECK_COLUMNS_SQL, {'db_name': Config.DB_NAME}).fetchall()
        }

        if 'weight_kg' in existing:
            skipped.append('weight_kg')
        else:
            conn.execute(_ADD_WEIGHT_KG_SQL)
            applied.append('weight_kg')

        if 'temperature_celsius' in existing:
            skipped.append('temperature_celsius')
        else:
            conn.execute(_ADD_TEMPERATURE_CELSIUS_SQL)
            applied.append('temperature_celsius')

    print(f"Migration complete against database '{Config.DB_NAME}'.")
    if applied:
        print(f"  Added columns: {', '.join(applied)}")
    if skipped:
        print(f"  Already present, skipped: {', '.join(skipped)}")
    if not applied:
        print("  Nothing to do, schema is already up to date.")


if __name__ == '__main__':
    main()
