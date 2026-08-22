"""Idempotent migration for the clinical-gaps feature set:
- appointments.status enum gains 'deferred' (alongside pending/completed/overdue)
- appointments.deferral_reason (nullable text)
- vaccinations.adverse_event_reported / adverse_event_severity /
  adverse_event_description / adverse_event_date

Uses the app's existing config (same env-var-driven DB connection as
config.Config, no hardcoded credentials). Checks INFORMATION_SCHEMA.COLUMNS
first and only ALTERs whatever is missing, so it's safe to run repeatedly.

The status enum change specifically inspects COLUMN_TYPE and only widens the
enum if 'deferred' isn't already one of its values. MODIFY COLUMN with a enum
definition that keeps every existing label in place and only appends a new
one does not alter, reorder, or lose any existing row's current status value
- MySQL enums are matched by label, not position, when the column already
holds one of the retained labels.

Run once by hand on the live database, e.g. via the Azure App Service SSH
console:
    python scripts/migrate_clinical_gaps.py
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text

from config import Config

_CHECK_APPOINTMENTS_COLUMNS_SQL = text("""
    SELECT COLUMN_NAME, COLUMN_TYPE FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = :db_name
      AND TABLE_NAME = 'appointments'
      AND COLUMN_NAME IN ('status', 'deferral_reason')
""")

_CHECK_VACCINATIONS_COLUMNS_SQL = text("""
    SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = :db_name
      AND TABLE_NAME = 'vaccinations'
      AND COLUMN_NAME IN ('adverse_event_reported', 'adverse_event_severity',
                           'adverse_event_description', 'adverse_event_date')
""")

_ALTER_STATUS_ENUM_SQL = text(
    "ALTER TABLE appointments MODIFY COLUMN status "
    "ENUM('pending','completed','overdue','deferred') NOT NULL DEFAULT 'pending'"
)

_ADD_DEFERRAL_REASON_SQL = text(
    "ALTER TABLE appointments ADD COLUMN deferral_reason TEXT NULL"
)

_ADD_ADVERSE_EVENT_REPORTED_SQL = text(
    "ALTER TABLE vaccinations ADD COLUMN adverse_event_reported BOOLEAN NOT NULL DEFAULT FALSE"
)
_ADD_ADVERSE_EVENT_SEVERITY_SQL = text(
    "ALTER TABLE vaccinations ADD COLUMN adverse_event_severity ENUM('mild','moderate','severe') NULL"
)
_ADD_ADVERSE_EVENT_DESCRIPTION_SQL = text(
    "ALTER TABLE vaccinations ADD COLUMN adverse_event_description TEXT NULL"
)
_ADD_ADVERSE_EVENT_DATE_SQL = text(
    "ALTER TABLE vaccinations ADD COLUMN adverse_event_date DATE NULL"
)


def main():
    engine = create_engine(Config.SQLALCHEMY_DATABASE_URI, **Config.SQLALCHEMY_ENGINE_OPTIONS)

    applied = []
    skipped = []

    with engine.begin() as conn:
        # --- appointments.status enum + deferral_reason ---
        apt_columns = {
            row[0]: row[1] for row in
            conn.execute(_CHECK_APPOINTMENTS_COLUMNS_SQL, {'db_name': Config.DB_NAME}).fetchall()
        }

        existing_enum_values = set(re.findall(r"'([^']*)'", apt_columns.get('status', '')))
        if 'deferred' in existing_enum_values:
            skipped.append("appointments.status (enum already includes 'deferred')")
        else:
            conn.execute(_ALTER_STATUS_ENUM_SQL)
            applied.append("appointments.status (widened enum to add 'deferred')")

        if 'deferral_reason' in apt_columns:
            skipped.append('appointments.deferral_reason')
        else:
            conn.execute(_ADD_DEFERRAL_REASON_SQL)
            applied.append('appointments.deferral_reason')

        # --- vaccinations adverse-event columns ---
        vax_columns = {
            row[0] for row in
            conn.execute(_CHECK_VACCINATIONS_COLUMNS_SQL, {'db_name': Config.DB_NAME}).fetchall()
        }

        if 'adverse_event_reported' in vax_columns:
            skipped.append('vaccinations.adverse_event_reported')
        else:
            conn.execute(_ADD_ADVERSE_EVENT_REPORTED_SQL)
            applied.append('vaccinations.adverse_event_reported')

        if 'adverse_event_severity' in vax_columns:
            skipped.append('vaccinations.adverse_event_severity')
        else:
            conn.execute(_ADD_ADVERSE_EVENT_SEVERITY_SQL)
            applied.append('vaccinations.adverse_event_severity')

        if 'adverse_event_description' in vax_columns:
            skipped.append('vaccinations.adverse_event_description')
        else:
            conn.execute(_ADD_ADVERSE_EVENT_DESCRIPTION_SQL)
            applied.append('vaccinations.adverse_event_description')

        if 'adverse_event_date' in vax_columns:
            skipped.append('vaccinations.adverse_event_date')
        else:
            conn.execute(_ADD_ADVERSE_EVENT_DATE_SQL)
            applied.append('vaccinations.adverse_event_date')

    print(f"Migration complete against database '{Config.DB_NAME}'.")
    if applied:
        print("  Applied:")
        for item in applied:
            print(f"    - {item}")
    if skipped:
        print("  Already present, skipped:")
        for item in skipped:
            print(f"    - {item}")
    if not applied:
        print("  Nothing to do, schema is already up to date.")


if __name__ == '__main__':
    main()
