"""
ETL pipeline — summarizes raw request_log and error_log data into a
daily_stats table, so Power BI (or anyone else) can see trends at a
glance without scanning every individual row.

Extract  -> reads raw rows from request_log and error_log
Transform -> aggregates them by day
Load     -> writes the summary into daily_stats (creates the table if needed)

Works against either database, same pattern as app.py:
- If NEON_DATABASE_URL is set (e.g. in GitHub Actions, pointed at Neon) -> uses that
- Otherwise -> falls back to your local PostgreSQL, using DB_PASSWORD

Run manually with:  python etl_daily_stats.py
Runs automatically once a day via GitHub Actions (see .github/workflows/etl.yml)
"""
import os
from datetime import date
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()  # picks up .env when running locally; harmless if it doesn't exist (e.g. in CI)

# ==================== DATABASE CONNECTION (local or Neon) ====================
DATABASE_URL = os.environ.get("NEON_DATABASE_URL")

if DATABASE_URL:
    # Running in GitHub Actions, or DATABASE_URL was set manually — use Neon
    print("Connecting to: Neon (via DATABASE_URL)")
    engine = create_engine(DATABASE_URL)
else:
    # No DATABASE_URL set — fall back to local PostgreSQL
    DB_PASSWORD = os.environ.get("DB_PASSWORD")
    if not DB_PASSWORD:
        raise RuntimeError(
            "Neither DATABASE_URL nor DB_PASSWORD is set. "
            "Set DATABASE_URL to run against Neon, or DB_PASSWORD in .env to run locally."
        )
    print("Connecting to: local PostgreSQL")
    engine = create_engine(f'postgresql://postgres:{DB_PASSWORD}@localhost:your_localhost/your_db_name')
# ==================== END DATABASE CONNECTION ====================


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS daily_stats (
    id SERIAL PRIMARY KEY,
    stat_date DATE UNIQUE NOT NULL,
    total_requests INTEGER NOT NULL,
    successful_requests INTEGER NOT NULL,
    failed_requests INTEGER NOT NULL,
    error_rate NUMERIC(5,2) NOT NULL,
    avg_response_time_ms INTEGER,
    top_category VARCHAR(20),
    total_errors INTEGER NOT NULL,
    run_at TIMESTAMP DEFAULT NOW()
);
"""

# Extract + Transform, in one aggregation query
AGGREGATE_SQL = """
SELECT
    DATE(timestamp) AS stat_date,
    COUNT(*) AS total_requests,
    COUNT(*) FILTER (WHERE success = TRUE) AS successful_requests,
    COUNT(*) FILTER (WHERE success = FALSE) AS failed_requests,
    ROUND(100.0 * COUNT(*) FILTER (WHERE success = FALSE) / NULLIF(COUNT(*), 0), 2) AS error_rate,
    ROUND(AVG(response_time_ms)) AS avg_response_time_ms,
    MODE() WITHIN GROUP (ORDER BY category) AS top_category
FROM request_log
GROUP BY DATE(timestamp)
ORDER BY stat_date;
"""

ERROR_COUNT_SQL = """
SELECT DATE(timestamp) AS stat_date, COUNT(*) AS total_errors
FROM error_log
GROUP BY DATE(timestamp);
"""

# Load — insert or update one row per day
UPSERT_SQL = """
INSERT INTO daily_stats (
    stat_date, total_requests, successful_requests, failed_requests,
    error_rate, avg_response_time_ms, top_category, total_errors
)
VALUES (:stat_date, :total_requests, :successful_requests, :failed_requests,
        :error_rate, :avg_response_time_ms, :top_category, :total_errors)
ON CONFLICT (stat_date) DO UPDATE SET
    total_requests = EXCLUDED.total_requests,
    successful_requests = EXCLUDED.successful_requests,
    failed_requests = EXCLUDED.failed_requests,
    error_rate = EXCLUDED.error_rate,
    avg_response_time_ms = EXCLUDED.avg_response_time_ms,
    top_category = EXCLUDED.top_category,
    total_errors = EXCLUDED.total_errors,
    run_at = NOW();
"""


def run_etl():
    with engine.begin() as conn:
        conn.execute(text(CREATE_TABLE_SQL))

        daily_rows = conn.execute(text(AGGREGATE_SQL)).mappings().all()
        error_counts = {row["stat_date"]: row["total_errors"] for row in conn.execute(text(ERROR_COUNT_SQL)).mappings().all()}

        for row in daily_rows:
            conn.execute(text(UPSERT_SQL), {
                "stat_date": row["stat_date"],
                "total_requests": row["total_requests"],
                "successful_requests": row["successful_requests"],
                "failed_requests": row["failed_requests"],
                "error_rate": row["error_rate"] or 0,
                "avg_response_time_ms": row["avg_response_time_ms"],
                "top_category": row["top_category"],
                "total_errors": error_counts.get(row["stat_date"], 0),
            })

        print(f"ETL complete — {len(daily_rows)} day(s) summarized as of {date.today()}")


if __name__ == "__main__":
    run_etl()