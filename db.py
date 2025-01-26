import os
import psycopg2
from psycopg2.extras import Json
from dotenv import load_dotenv, find_dotenv
from typing import Dict, Any, List
import json

# Load environment variables
load_dotenv(find_dotenv())
DATABASE_URL = os.environ.get("DATABASE_URL")

def init_db():
    """Create all necessary tables if they don't exist."""
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    
    # Create shop_tokens table
    create_tokens_table = """
    CREATE TABLE IF NOT EXISTS shop_tokens (
        id SERIAL PRIMARY KEY,
        shop VARCHAR(255) UNIQUE NOT NULL,
        access_token TEXT NOT NULL,
        installed_at TIMESTAMP DEFAULT NOW()
    );
    """
    
    # Create products table with JSONB for better JSON handling
    create_products_table = """
    CREATE TABLE IF NOT EXISTS products (
        shop VARCHAR(255) NOT NULL,
        product_id TEXT NOT NULL,
        title TEXT,
        handle TEXT,
        created_at TIMESTAMP,
        updated_at TIMESTAMP,
        published_at TIMESTAMP,
        status TEXT,
        variants JSONB,
        images JSONB,
        options JSONB,
        product_type TEXT,
        tags TEXT,
        PRIMARY KEY (shop, product_id)
    );
    """
    
    try:
        cur.execute(create_tokens_table)
        cur.execute(create_products_table)
        conn.commit()
    except Exception as e:
        print(f"Error creating tables: {e}")
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()

async def store_product(shop: str, product: Dict[str, Any]):
    """Store a product in the PostgreSQL database"""
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    
    try:
        # Insert or update product
        upsert_sql = """
        INSERT INTO products (
            shop, product_id, title, handle, created_at, updated_at, 
            published_at, status, variants, images, options, product_type, 
            tags
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
        ) ON CONFLICT (shop, product_id) DO UPDATE SET
            title = EXCLUDED.title,
            handle = EXCLUDED.handle,
            created_at = EXCLUDED.created_at,
            updated_at = EXCLUDED.updated_at,
            published_at = EXCLUDED.published_at,
            status = EXCLUDED.status,
            variants = EXCLUDED.variants,
            images = EXCLUDED.images,
            options = EXCLUDED.options,
            product_type = EXCLUDED.product_type,
            tags = EXCLUDED.tags;
        """
        
        cur.execute(upsert_sql, (
            product['shop'],
            str(product['product_id']),
            product['title'],
            product['handle'],
            product['created_at'],
            product['updated_at'],
            product['published_at'],
            product['status'],
            Json(product['variants']),  # Using psycopg2.extras.Json for proper JSON handling
            Json(product['images']),
            Json(product['options']),
            product['product_type'],
            product['tags']
        ))
        
        conn.commit()
    except Exception as e:
        print(f"Error storing product: {e}")
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()

async def get_shop_products(shop: str) -> List[Dict[str, Any]]:
    """Retrieve all products for a shop from PostgreSQL"""
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    
    try:
        cur.execute("""
            SELECT 
                shop, product_id, title, handle, created_at, updated_at,
                published_at, status, variants, images, options, product_type, 
                tags
            FROM products 
            WHERE shop = %s
        """, (shop,))
        
        columns = [desc[0] for desc in cur.description]
        products = []
        
        for row in cur.fetchall():
            product = dict(zip(columns, row))
            # Convert timestamps to strings if needed
            for field in ['created_at', 'updated_at', 'published_at']:
                if product[field]:
                    product[field] = product[field].isoformat()
            products.append(product)
            
        return products
    except Exception as e:
        print(f"Error fetching products: {e}")
        raise
    finally:
        cur.close()
        conn.close()

def store_access_token(shop_domain: str, token: str):
    """Store shop access token"""
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    
    try:
        upsert_sql = """
        INSERT INTO shop_tokens (shop, access_token)
        VALUES (%s, %s)
        ON CONFLICT (shop) DO UPDATE
          SET access_token = EXCLUDED.access_token;
        """
        cur.execute(upsert_sql, (shop_domain, token))
        conn.commit()
    except Exception as e:
        print(f"Error storing access token: {e}")
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()

def get_access_token_for_shop(shop_domain: str) -> str | None:
    """Retrieve shop access token"""
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    
    try:
        select_sql = """
        SELECT access_token
        FROM shop_tokens
        WHERE shop = %s
        LIMIT 1
        """
        cur.execute(select_sql, (shop_domain,))
        row = cur.fetchone()
        return row[0] if row else None
    except Exception as e:
        print(f"Error retrieving access token: {e}")
        raise
    finally:
        cur.close()
        conn.close()