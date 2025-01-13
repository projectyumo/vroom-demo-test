import os
import random
import httpx
import logging
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv, find_dotenv
from db import init_db, store_access_token, get_access_token_for_shop, store_product, get_shop_products
from fastapi import BackgroundTasks

import hashlib
from urllib.parse import urlencode, quote

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s\n%(asctime)s',
    datefmt='%b %d %H:%M:%S'
)
logger = logging.getLogger(__name__)

load_dotenv(find_dotenv())

SHOPIFY_API_KEY = os.environ.get("SHOPIFY_API_KEY")
SHOPIFY_API_SECRET = os.environ.get("SHOPIFY_API_SECRET")
APP_URL = os.environ.get("APP_URL")

app = FastAPI()

# Basic CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def on_startup():
    """Initialize application"""
    logger.info("INFO: Initializing database...")
    init_db()

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("INFO: Application shutdown complete.")

async def ingest_products(shop: str, access_token: str):
    """
    Fetch and store all products for a shop
    """
    try:
        # Fetch all products
        products = await fetch_all_products(shop, access_token)

        # Process and store each product
        for product in products:
            processed_product = {
                "shop": shop,
                "product_id": product.get("id"),
                "title": product.get("title"),
                "handle": product.get("handle"),
                "created_at": product.get("created_at"),
                "updated_at": product.get("updated_at"),
                "published_at": product.get("published_at"),
                "status": product.get("status"),
                "variants": product.get("variants", []),
                "images": product.get("images", []),
                "options": product.get("options", []),
                "tags": product.get("tags")
            }

            # Store in database - implement this function in your db.py
            await store_product(shop, processed_product)

        return len(products)
    except Exception as e:
        print(f"Error ingesting products for {shop}: {str(e)}")
        raise

def verify_hmac(params: dict) -> bool:
    """Verify the HMAC signature from Shopify"""
    try:
        # Remove hmac from params if it exists
        hmac_value = params.pop('hmac', '')
        
        # Sort and join parameters
        sorted_params = "&".join([
            f"{key}={value}"
            for key, value in sorted(params.items())
        ])
        
        # Calculate HMAC
        calculated_hmac = hmac.new(
            SHOPIFY_API_SECRET.encode('utf-8'),
            sorted_params.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(calculated_hmac, hmac_value)
    except Exception as e:
        logger.error(f"ERROR: HMAC verification failed: {str(e)}")
        return False

@app.get("/")
async def root(request: Request):
    """Handle initial app load and installation"""
    params = dict(request.query_params)
    logger.info(f"INFO: Received request with params: {params}")
    
    # Get the shop parameter
    shop = params.get('shop')
    if not shop:
        logger.error("ERROR: Missing shop parameter")
        return JSONResponse({"error": "Missing shop parameter"})
        
    # Ensure shop is a valid .myshopify.com domain
    if not shop.endswith('.myshopify.com'):
        shop = f"{shop}.myshopify.com"
    
    # Check for an existing access token
    access_token = get_access_token_for_shop(shop)
    
    # If we have embedded=1, it's an app load within Shopify Admin
    if params.get('embedded') == '1':
        # Verify HMAC if present
        if 'hmac' in params:
            is_valid = verify_hmac(params.copy())
            if not is_valid:
                logger.error("ERROR: Invalid HMAC signature")
                raise HTTPException(status_code=400, detail="Invalid HMAC signature")
        
        # If we have a valid session, return app
        if access_token:
            logger.info(f"INFO: Valid session found for {shop}")
            return JSONResponse({
                "status": "success",
                "message": "App is installed and authorized",
                "shop": shop
            })
    
    # No valid session, start OAuth
    logger.info(f"INFO: Redirecting to OAuth for {shop}")
    return RedirectResponse(url=f"/install?shop={quote(shop)}")

@app.get("/install")
async def install(request: Request):
    """Handle app installation"""
    shop = request.query_params.get("shop")
    if not shop:
        logger.error("ERROR: Missing shop parameter in install route")
        raise HTTPException(status_code=400, detail="Missing shop parameter")

    # Ensure shop is a valid .myshopify.com domain
    if not shop.endswith('.myshopify.com'):
        shop = f"{shop}.myshopify.com"

    # Construct OAuth URL
    scopes = "read_products,write_products"
    redirect_uri = f"{APP_URL}/callback"
    nonce = os.urandom(16).hex()
    
    install_url = f"https://{shop}/admin/oauth/authorize?" + urlencode({
        'client_id': SHOPIFY_API_KEY,
        'scope': scopes,
        'redirect_uri': redirect_uri,
        'state': nonce
    })
    
    logger.info(f"INFO: Redirecting to Shopify OAuth: {install_url}")
    return RedirectResponse(url=install_url)

@app.get("/callback")
async def callback(request: Request, background_tasks: BackgroundTasks):
    """Handle OAuth callback and verify scopes"""
    logger.info("INFO: Starting OAuth callback...")
    shop = request.query_params.get("shop")
    code = request.query_params.get("code")
    host = request.query_params.get("host")
    
    if not all([shop, code]):
        raise HTTPException(status_code=400, detail="Missing required parameters")

    try:
        # Get access token with scope verification
        token_url = f"https://{shop}/admin/oauth/access_token"
        async with httpx.AsyncClient() as client:
            response = await client.post(
                token_url,
                json={
                    'client_id': SHOPIFY_API_KEY,
                    'client_secret': SHOPIFY_API_SECRET,
                    'code': code
                }
            )
            
            if response.status_code != 200:
                logger.error(f"ERROR: Token exchange failed: {response.text}")
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Failed to get access token: {response.text}"
                )
            
            data = response.json()
            access_token = data.get('access_token')
            granted_scopes = data.get('scope', '').split(',')
            
            logger.info(f"INFO: Granted scopes: {granted_scopes}")
            
            # Verify required scopes
            required_scopes = {'read_products', 'write_products'}
            if not required_scopes.issubset(set(granted_scopes)):
                missing_scopes = required_scopes - set(granted_scopes)
                logger.error(f"ERROR: Missing required scopes: {missing_scopes}")
                raise HTTPException(
                    status_code=403,
                    detail=f"Missing required scopes: {missing_scopes}"
                )

        # Store the access token
        logger.info("INFO: Storing access token...")
        store_access_token(shop, access_token)
        logger.info("INFO: Access token stored successfully")

        # Verify access by making a test API call
        test_url = f"https://{shop}/admin/api/2024-01/products/count.json"
        async with httpx.AsyncClient() as client:
            test_response = await client.get(
                test_url,
                headers={
                    'X-Shopify-Access-Token': access_token,
                    'Content-Type': 'application/json'
                }
            )
            
            if test_response.status_code != 200:
                logger.error(f"ERROR: API test failed: {test_response.text}")
                raise HTTPException(
                    status_code=test_response.status_code,
                    detail=f"API access test failed: {test_response.text}"
                )
            
            logger.info(f"INFO: API test successful: {test_response.text}")

        # Add product fetch to background tasks
        background_tasks.add_task(background_fetch_products, shop, access_token)
        logger.info("INFO: Product fetch scheduled in background")

        # Construct the redirect URL
        if host:
            redirect_url = f"https://{host}/apps/{SHOPIFY_API_KEY}"
        else:
            redirect_url = f"https://{shop}/admin/apps/{SHOPIFY_API_KEY}"
            
        logger.info(f"INFO: Redirecting to: {redirect_url}")
        
        return RedirectResponse(
            url=redirect_url,
            status_code=302
        )

    except Exception as e:
        logger.error(f"ERROR: Error in callback: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

async def background_fetch_products(shop: str, access_token: str):
    """Background task to fetch and store products"""
    logger.info(f"INFO: Starting background product fetch for {shop}...")
    try:
        products = await fetch_all_products(shop, access_token)
        logger.info(f"INFO: Successfully fetched {len(products)} products")

        # Store products in database
        for product in products:
            processed_product = {
                "shop": shop,
                "product_id": product.get("id"),
                "title": product.get("title"),
                "handle": product.get("handle"),
                "created_at": product.get("created_at"),
                "updated_at": product.get("updated_at"),
                "published_at": product.get("published_at"),
                "status": product.get("status"),
                "variants": product.get("variants", []),
                "images": product.get("images", []),
                "options": product.get("options", []),
                "tags": product.get("tags")
            }
            await store_product(shop, processed_product)
        logger.info(f"INFO: Successfully stored all products for {shop}")
    except Exception as e:
        logger.error(f"ERROR: Error in background product fetch: {str(e)}")

async def fetch_all_products(shop: str, access_token: str) -> list:
    """Fetch all products from a shop using pagination"""
    all_products = []
    page_info = None
    
    async with httpx.AsyncClient() as client:
        while True:
            url = f"https://{shop}/admin/api/2024-01/products.json?limit=250"
            if page_info:
                url += f"&page_info={page_info}"
                
            headers = {
                "X-Shopify-Access-Token": access_token,
                "Content-Type": "application/json"
            }
            
            logger.info(f"INFO: Fetching products page from {url}")
            response = await client.get(url, headers=headers)
            
            if response.status_code != 200:
                error_msg = f"Failed to fetch products: {response.text}"
                logger.error(f"ERROR: {error_msg}")
                raise HTTPException(status_code=response.status_code, detail=error_msg)
            
            data = response.json()
            page_products = data.get("products", [])
            all_products.extend(page_products)
            logger.info(f"INFO: Fetched {len(page_products)} products on this page")
            
            # Check for next page
            link_header = response.headers.get("Link", "")
            if 'rel="next"' not in link_header:
                break
                
            # Extract page_info for next page
            page_info = link_header.split("page_info=")[1].split(">")[0]
    
    return all_products