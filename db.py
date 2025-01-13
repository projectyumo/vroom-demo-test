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
    """Initialize database and create required tables"""
    logger.info("INFO: Initializing database...")
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        
        # Create the shop_tokens table if it doesn't exist
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
        logger.info("INFO: Database initialized successfully")
        
    except Exception as e:
        logger.error(f"ERROR: Failed to initialize database: {str(e)}")
        raise
    finally:
        if 'cur' in locals():
            cur.close()
        if 'conn' in locals():
            conn.close()

def store_access_token(shop_domain: str, token: str):
    """Store or update access token for a shop"""
    logger.info(f"INFO: Storing token for shop: {shop_domain}")
    
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        
        # Insert or update token
        upsert_sql = """
        INSERT INTO shop_tokens (shop, access_token)
        VALUES (%s, %s)
        ON CONFLICT (shop) DO UPDATE
            SET access_token = EXCLUDED.access_token,
                installed_at = NOW();
        """
        cur.execute(upsert_sql, (shop_domain, token))
        conn.commit()
        
        # Verify the token was stored
        cur.execute("SELECT access_token FROM shop_tokens WHERE shop = %s", (shop_domain,))
        result = cur.fetchone()
        
        if result and result[0] == token:
            logger.info(f"INFO: Token successfully stored for {shop_domain}")
        else:
            raise Exception("Token verification failed")
            
    except Exception as e:
        logger.error(f"ERROR: Failed to store access token: {str(e)}")
        raise
    finally:
        if 'cur' in locals():
            cur.close()
        if 'conn' in locals():
            conn.close()

def get_access_token_for_shop(shop_domain: str) -> str | None:
    """Retrieve access token for a shop"""
    logger.info(f"INFO: Retrieving token for shop: {shop_domain}")
    
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        
        cur.execute("""
            SELECT access_token
            FROM shop_tokens
            WHERE shop = %s
            LIMIT 1
        """, (shop_domain,))
        
        result = cur.fetchone()
        
        if result:
            logger.info(f"INFO: Token found for {shop_domain}")
            return result[0]
        else:
            logger.warning(f"WARNING: No token found for {shop_domain}")
            return None
            
    except Exception as e:
        logger.error(f"ERROR: Failed to retrieve access token: {str(e)}")
        raise
    finally:
        if 'cur' in locals():
            cur.close()
        if 'conn' in locals():
            conn.close()

# Product-related functions remain the same
async def store_product(shop: str, product: Dict[str, Any]):
    """Store a product in the database"""
    conn = sqlite3.connect('shopify_app.db')
    cursor = conn.cursor()
    
    try:
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
        logger.info(f"INFO: Stored product {product_data['title']} for {shop}")
    finally:
        conn.close()

async def get_shop_products(shop: str) -> list:
    """Retrieve products for a shop"""
    conn = sqlite3.connect('shopify_app.db')
    cursor = conn.cursor()
    
    try:
        cursor.execute(
            'SELECT * FROM products WHERE shop = ?',
            (shop,)
        )
        
        columns = [description[0] for description in cursor.description]
        products = []
        
        for row in cursor.fetchall():
            product = dict(zip(columns, row))
            product['variants'] = json.loads(product['variants'])
            product['images'] = json.loads(product['images'])
            product['options'] = json.loads(product['options'])
            products.append(product)
            
        logger.info(f"INFO: Retrieved {len(products)} products for {shop}")
        return products
    finally:
        conn.close()