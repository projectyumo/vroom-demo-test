import os
import psycopg2
import sqlite3
import json
import logging
from typing import Dict, Any
from dotenv import load_dotenv, find_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s\n%(asctime)s',
    datefmt='%b %d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv(find_dotenv())
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
    logger.info("INFO: Database initialized successfully")

def store_access_token(shop_domain: str, token: str):
    logger.info(f"INFO: Storing token for {shop_domain}")
    try:
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
        logger.info("INFO: Token stored successfully")
    except Exception as e:
        logger.error(f"ERROR in store_access_token: {e}")
        raise

async def store_product(shop: str, product: Dict[str, Any]):
    """Store a product in the database"""
    conn = sqlite3.connect('shopify_app.db')
    cursor = conn.cursor()
    
    try:
        # Create products table if it doesn't exist
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS products
        (shop TEXT,
         product_id TEXT,
         title TEXT,
         handle TEXT,
         created_at TEXT,
         updated_at TEXT,
         published_at TEXT,
         status TEXT,
         variants TEXT,
         images TEXT,
         options TEXT,
         tags TEXT,
         PRIMARY KEY (shop, product_id))
        ''')
        
        # Convert lists and dictionaries to JSON strings
        product_data = product.copy()
        product_data['variants'] = json.dumps(product_data['variants'])
        product_data['images'] = json.dumps(product_data['images'])
        product_data['options'] = json.dumps(product_data['options'])
        
        cursor.execute('''
        INSERT OR REPLACE INTO products
        (shop, product_id, title, handle, created_at, updated_at, published_at,
         status, variants, images, options, tags)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            product_data['shop'],
            str(product_data['product_id']),
            product_data['title'],
            product_data['handle'],
            product_data['created_at'],
            product_data['updated_at'],
            product_data['published_at'],
            product_data['status'],
            product_data['variants'],
            product_data['images'],
            product_data['options'],
            product_data['tags']
        ))
        
        conn.commit()
        logger.info(f"INFO: Stored product {product_data['title']} for shop {shop}")
    except Exception as e:
        logger.error(f"ERROR: Failed to store product: {str(e)}")
        raise
    finally:
        conn.close()

def get_access_token_for_shop(shop_domain: str) -> str | None:
    """Retrieves the stored access token for a shop."""
    try:
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
        
        if row:
            logger.info(f"INFO: Retrieved access token for {shop_domain}")
            return row[0]
        else:
            logger.warning(f"WARNING: No access token found for {shop_domain}")
            return None
    except Exception as e:
        logger.error(f"ERROR: Failed to get access token: {str(e)}")
        raise