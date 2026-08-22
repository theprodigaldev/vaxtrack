"""Idempotent migration: add appointments.checked_in_at / checked_in_by /
checked_in_facility_id.

Uses the app's existing config (same env-var-driven DB connection as
config.Config, no hardcoded credentials). Checks INFORMATION_SCHEMA.COLUMNS
first and only ALTERs whichever column is missing, so it's safe to run
repeatedly and never touches existing data.

Run once by hand on the live database, e.g. via the Azure App Service SSH
console:
    python scripts/migrate_checkin_columns.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text

from config import Config

_CHECK_COLUMNS_SQL = text("""
    SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = :db_name
      AND TABLE_NAME = 'appointments'
      AND COLUMN_NAME IN ('checked_in_at', 'checked_in_by', 'checked_in_facility_id')
""")

_ADD_CHECKED_IN_AT_SQL = text(
    "ALTER TABLE appointments ADD COLUMN checked_in_at DATETIME NULL"
)

_ADD_CHECKED_IN_BY_SQL = text(
    "ALTER TABLE appointments "
    "ADD COLUMN checked_in_by INT NULL, "
    "ADD CONSTRAINT fk_appointments_checked_in_by "
    "FOREIGN KEY (checked_in_by) REFERENCES users(user_id)"
)

_ADD_CHECKED_IN_FACILITY_ID_SQL = text(
    "ALTER TABLE appointments "
    "ADD COLUMN checked_in_facility_id INT NULL, "
    "ADD CONSTRAINT fk_appointments_checked_in_facility_id "
    "FOREIGN KEY (checked_in_facility_id) REFERENCES facilities(facility_id)"
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

        if 'checked_in_at' in existing:
            skipped.append('checked_in_at')
        else:
            conn.execute(_ADD_CHECKED_IN_AT_SQL)
            applied.append('checked_in_at')

        if 'checked_in_by' in existing:
            skipped.append('checked_in_by')
        else:
            conn.execute(_ADD_CHECKED_IN_BY_SQL)
            applied.append('checked_in_by')

        if 'checked_in_facility_id' in existing:
            skipped.append('checked_in_facility_id')
        else:
            conn.execute(_ADD_CHECKED_IN_FACILITY_ID_SQL)
            applied.append('checked_in_facility_id')

    print(f"Migration complete against database '{Config.DB_NAME}'.")
    if applied:
        print(f"  Added columns: {', '.join(applied)}")
    if skipped:
        print(f"  Already present, skipped: {', '.join(skipped)}")
    if not applied:
        print("  Nothing to do, schema is already up to date.")


if __name__ == '__main__':
    main()
