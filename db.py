import os
import psycopg2
from dotenv import load_dotenv, find_dotenv
import sqlite3
import json
from typing import Dict, Any
import aiosqlite

# Load environment variables from .env (if running locally).
# On Railway, these are typically injected automatically, but calling load_dotenv won't hurt.
load_dotenv(find_dotenv())

# You can either use DATABASE_URL directly (which many libraries parse automatically),
# or build a connection string from PGHOST, PGPORT, etc.
DATABASE_URL = os.environ.get("DATABASE_URL")

async def init_db():
    """Initialize the database with async support"""
    async with aiosqlite.connect('shopify_app.db') as db:
        await db.execute('''
        CREATE TABLE IF NOT EXISTS access_tokens
        (shop TEXT PRIMARY KEY, access_token TEXT)
        ''')
        await db.commit()

async def store_access_token(shop: str, access_token: str):
    """Store access token asynchronously"""
    async with aiosqlite.connect('shopify_app.db') as db:
        await db.execute(
            'INSERT OR REPLACE INTO access_tokens (shop, access_token) VALUES (?, ?)',
            (shop, access_token)
        )
        await db.commit()
        
async def get_access_token_for_shop(shop: str) -> str:
    """Get access token asynchronously"""
    async with aiosqlite.connect('shopify_app.db') as db:
        async with db.execute(
            'SELECT access_token FROM access_tokens WHERE shop = ?',
            (shop,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None
        
    
async def store_product(shop: str, product: dict):
    """Store a product asynchronously"""
    async with aiosqlite.connect('shopify_app.db') as db:
        await db.execute('''
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
        
        # Convert lists and dicts to JSON strings
        product_data = product.copy()
        for field in ['variants', 'images', 'options']:
            if isinstance(product_data.get(field), (list, dict)):
                product_data[field] = json.dumps(product_data[field])
        
        await db.execute('''
        INSERT OR REPLACE INTO products
        (shop, product_id, title, handle, created_at, updated_at, 
         published_at, status, variants, images, options, tags)
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
        await db.commit()

async def get_shop_products(shop: str) -> list:
    """Get all products for a shop asynchronously"""
    async with aiosqlite.connect('shopify_app.db') as db:
        async with db.execute(
            'SELECT * FROM products WHERE shop = ?',
            (shop,)
        ) as cursor:
            rows = await cursor.fetchall()
            # Get column names
            columns = [description[0] for description in cursor.description]
            products = []
            for row in rows:
                product = dict(zip(columns, row))
                # Convert JSON strings back to objects
                for field in ['variants', 'images', 'options']:
                    if product.get(field):
                        product[field] = json.loads(product[field])
                products.append(product)
            return products

