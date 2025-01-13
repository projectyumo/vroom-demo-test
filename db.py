import aiosqlite
import json

DATABASE_FILE = "shopify_app.db"


async def init_db():
    async with aiosqlite.connect(DATABASE_FILE) as db:
        await db.execute('''
        CREATE TABLE IF NOT EXISTS access_tokens (
            shop TEXT PRIMARY KEY,
            access_token TEXT
        )
        ''')
        await db.execute('''
        CREATE TABLE IF NOT EXISTS products (
            shop TEXT,
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
            PRIMARY KEY (shop, product_id)
        )
        ''')
        await db.commit()


async def store_access_token(shop: str, access_token: str):
    async with aiosqlite.connect(DATABASE_FILE) as db:
        await db.execute(
            'INSERT OR REPLACE INTO access_tokens (shop, access_token) VALUES (?, ?)',
            (shop, access_token)
        )
        await db.commit()


async def get_access_token_for_shop(shop: str):
    async with aiosqlite.connect(DATABASE_FILE) as db:
        async with db.execute('SELECT access_token FROM access_tokens WHERE shop = ?', (shop,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None


async def store_product(shop: str, product: dict):
    async with aiosqlite.connect(DATABASE_FILE) as db:
        await db.execute(
            '''
            INSERT OR REPLACE INTO products (
                shop, product_id, title, handle, created_at, updated_at,
                published_at, status, variants, images, options, tags
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                shop, product["product_id"], product["title"], product["handle"],
                product["created_at"], product["updated_at"], product["published_at"],
                product["status"], json.dumps(product["variants"]), json.dumps(product["images"]),
                json.dumps(product["options"]), product["tags"]
            )
        )
        await db.commit()


async def get_shop_products(shop: str):
    async with aiosqlite.connect(DATABASE_FILE) as db:
        async with db.execute('SELECT * FROM products WHERE shop = ?', (shop,)) as cursor:
            rows = await cursor.fetchall()
            columns = [description[0] for description in cursor.description]
            return [dict(zip(columns, row)) for row in rows]
