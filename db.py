import os
import psycopg2
from dotenv import load_dotenv, find_dotenv

# Load environment variables from .env (if running locally).
# On Railway, these are typically injected automatically, but calling load_dotenv won't hurt.
load_dotenv(find_dotenv())

# You can either use DATABASE_URL directly (which many libraries parse automatically),
# or build a connection string from PGHOST, PGPORT, etc.
DATABASE_URL = os.environ.get("DATABASE_URL")

def init_db():
    """Create the table if it doesn't exist."""
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    create_table_sql = """
    CREATE TABLE IF NOT EXISTS shop_tokens (
      id SERIAL PRIMARY KEY,
      shop VARCHAR(255) UNIQUE NOT NULL,
      access_token TEXT NOT NULL,
      installed_at TIMESTAMP DEFAULT NOW()
    );
    """
    cur.execute(create_table_sql)
    conn.commit()
    cur.close()
    conn.close()

def store_access_token(shop_domain: str, token: str):
    """Inserts or updates the token for a given shop."""
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    upsert_sql = """
    INSERT INTO shop_tokens (shop, access_token)
    VALUES (%s, %s)
    ON CONFLICT (shop) DO UPDATE
      SET access_token = EXCLUDED.access_token;
    """
    cur.execute(upsert_sql, (shop_domain, token))
    conn.commit()
    cur.close()
    conn.close()

def get_access_token_for_shop(shop_domain: str) -> str | None:
    """Retrieves the stored access token for a shop."""
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    select_sql = """
    SELECT access_token
    FROM shop_tokens
    WHERE shop = %s
    LIMIT 1
    """
    cur.execute(select_sql, (shop_domain,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row[0] if row else None

