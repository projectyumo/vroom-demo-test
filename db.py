import os
import psycopg2
from dotenv import load_dotenv, find_dotenv
        conn.close()


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
    
async def store_product(shop: str, product: Dict[str, Any]):
    """
    Store a product in the database
    """
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
        
        # Insert or replace product
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
    finally:
        conn.close()

async def get_shop_products(shop: str) -> list:
    """
    Retrieve all products for a shop
    """
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
            # Convert JSON strings back to Python objects
            product['variants'] = json.loads(product['variants'])
            product['images'] = json.loads(product['images'])
            product['options'] = json.loads(product['options'])
            products.append(product)
            
        return products
    finally:
        conn.close()

def store_access_token(shop_domain: str, token: str):
    print(f"DEBUG: Storing token for {shop_domain}: {token}")
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
        print("DEBUG: Token stored successfully.")
    except Exception as e:
        print(f"ERROR in store_access_token: {e}")
        raise


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

