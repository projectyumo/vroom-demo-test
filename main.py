import os
import random
import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv, find_dotenv
from db import init_db, store_access_token, get_access_token_for_shop, store_product, get_shop_products
from urllib.parse import urlencode
from fastapi import BackgroundTasks

load_dotenv(find_dotenv())

SHOPIFY_API_KEY = os.environ.get("SHOPIFY_API_KEY")
SHOPIFY_API_SECRET = os.environ.get("SHOPIFY_API_SECRET")
APP_URL = os.environ.get("APP_URL")  # Your ngrok URL for testing

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
    print("Initializing database...")
    init_db()

@app.get("/")
async def root(request: Request):
    """Initial entry point"""
    shop = request.query_params.get("shop")
    
    if not shop:
        return JSONResponse({"error": "Missing shop parameter"})

    # Check if we have an access token
    access_token = get_access_token_for_shop(shop)
    
    # If no access token, redirect to install
    if not access_token:
        return RedirectResponse(url=f"/install?shop={shop}")

    # Return simple success response
    return JSONResponse({
        "status": "success",
        "message": "App is installed and authorized",
        "shop": shop
    })

@app.get("/install")
async def install(request: Request):
    """
    Step 1: App installation begins here.
    The merchant clicks install, and we redirect them to Shopify's OAuth screen.
    """
    shop = request.query_params.get("shop")
    if not shop:
        raise HTTPException(status_code=400, detail="Missing shop parameter")

    # Construct the authorization URL with required scopes
    scopes = "read_products,write_products"  # Explicitly request product access
    redirect_uri = f"{os.environ.get('APP_URL')}/callback"
    
    install_url = f"https://{shop}/admin/oauth/authorize?" + urlencode({
        'client_id': SHOPIFY_API_KEY,
        'scope': scopes,
        'redirect_uri': redirect_uri,
    })
    
    print(f"Redirecting to Shopify OAuth: {install_url}")
    return RedirectResponse(url=install_url)

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
            
            print(f"Fetching products page from {url}")
            response = await client.get(url, headers=headers)
            
            if response.status_code != 200:
                error_msg = f"Failed to fetch products: {response.text}"
                print(error_msg)
                raise HTTPException(status_code=response.status_code, detail=error_msg)
            
            data = response.json()
            page_products = data.get("products", [])
            all_products.extend(page_products)
            print(f"Fetched {len(page_products)} products on this page")
            
            # Check for next page
            link_header = response.headers.get("Link", "")
            if 'rel="next"' not in link_header:
                break
                
            # Extract page_info for next page
            page_info = link_header.split("page_info=")[1].split(">")[0]
    
    return all_products

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

@app.get("/install")
async def install(request: Request):
    """
    Step 1: App installation begins here.
    The merchant clicks install, and we redirect them to Shopify's OAuth screen.
    """
    shop = request.query_params.get("shop")
    if not shop:
        raise HTTPException(status_code=400, detail="Missing shop parameter")

    # Construct the authorization URL with required scopes
    scopes = "read_products,write_products"  # Explicitly request product access
    redirect_uri = f"{os.environ.get('APP_URL')}/callback"
    
    install_url = f"https://{shop}/admin/oauth/authorize?" + urlencode({
        'client_id': SHOPIFY_API_KEY,
        'scope': scopes,
        'redirect_uri': redirect_uri,
    })
    
    print(f"Redirecting to Shopify OAuth: {install_url}")
    return RedirectResponse(url=install_url)

async def background_fetch_products(shop: str, access_token: str):
    """Background task to fetch and store products"""
    print(f"Starting background product fetch for {shop}...")
    try:
        products = await fetch_all_products(shop, access_token)
        print(f"Successfully fetched {len(products)} products")

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
        print(f"Successfully stored all products for {shop}")
    except Exception as e:
        print(f"Error in background product fetch: {str(e)}")

        
@app.get("/callback")
async def callback(request: Request, background_tasks: BackgroundTasks):
    """Handle OAuth callback and trigger background product ingestion"""
    print("Starting OAuth callback...")
    shop = request.query_params.get("shop")
    code = request.query_params.get("code")
    host = request.query_params.get("host")
    
    if not all([shop, code]):
        raise HTTPException(status_code=400, detail="Missing required parameters")

    try:
        # Get and store access token
        print("Getting access token...")
        access_token = await get_access_token(shop, code)
        print("Successfully got access token")
        
        # Store the access token
        print("Storing access token...")
        store_access_token(shop, access_token)
        print("Access token stored successfully")

        # Add product fetch to background tasks
        background_tasks.add_task(background_fetch_products, shop, access_token)
        print("Product fetch scheduled in background")

        # Construct the proper redirect URL
        if host:
            redirect_url = f"https://{host}/apps/{SHOPIFY_API_KEY}"
        else:
            redirect_url = f"https://{shop}/admin/apps/{SHOPIFY_API_KEY}"
            
        print(f"Redirecting to: {redirect_url}")
        
        # Use 302 status code for temporary redirect
        return RedirectResponse(
            url=redirect_url,
            status_code=302
        )

    except Exception as e:
        print(f"Error in callback: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
        
# Add an endpoint to manually trigger re-ingestion
@app.post("/api/refresh-products")
async def refresh_products(request: Request):
    """Manually trigger product refresh for a shop"""
    shop = request.query_params.get("shop")
    
    if not shop:
        return JSONResponse({"error": "Missing shop parameter"})
    
    access_token = get_access_token_for_shop(shop)
    if not access_token:
        return JSONResponse({"error": "Shop not authorized"})
    
    try:
        product_count = await ingest_products(shop, access_token)
        return JSONResponse({
            "success": True,
            "message": f"Successfully refreshed {product_count} products"
        })
    except Exception as e:
        return JSONResponse({
            "success": False,
            "error": str(e)
        })

async def get_access_token(shop: str, code: str) -> str:
    """Exchange temporary code for permanent access token"""
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
            raise HTTPException(
                status_code=response.status_code,
                detail=f"Failed to get access token: {response.text}"
            )
            
        data = response.json()
        return data.get('access_token')

@app.get("/api/products")
async def get_products(request: Request):
    """
    API endpoint to fetch products from a shop.
    Requires shop parameter and valid access token.
    """
    shop = request.query_params.get("shop")
    if not shop:
        return JSONResponse({"error": "Missing shop parameter"})

    access_token = get_access_token_for_shop(shop)
    if not access_token:
        return JSONResponse({"error": "Shop not authorized"})

    url = f"https://{shop}/admin/api/2024-01/products.json"
    
    async with httpx.AsyncClient() as client:
        response = await client.get(
            url,
            headers={
                'X-Shopify-Access-Token': access_token,
                'Content-Type': 'application/json'
            }
        )
        
        if response.status_code != 200:
            return JSONResponse({"error": f"Failed to fetch products: {response.text}"})
            
        return response.json()

# Add an endpoint to check ingestion status (optional)
@app.get("/api/ingestion-status")
async def check_ingestion_status(request: Request):
    """Check product ingestion status for a shop"""
    shop = request.query_params.get("shop")
    if not shop:
        return JSONResponse({"error": "Missing shop parameter"})
    
    try:
        products = await get_shop_products(shop)
        return JSONResponse({
            "status": "success",
            "product_count": len(products),
            "shop": shop
        })
    except Exception as e:
        return JSONResponse({
            "status": "error",
            "message": str(e),
            "shop": shop
        })
    
@app.get("/random-products")
async def random_products(request: Request):
    """Get random products from our local database"""
    shop = request.query_params.get("shop")
    if not shop:
        return JSONResponse({"error": "Missing shop parameter"})

    # Get products from local database
    try:
        products = await get_shop_products(shop)
    except Exception as e:
        print(f"Error fetching products from database: {str(e)}")
        return JSONResponse({"error": "Failed to fetch products from database"})

    if not products:
        # If no products in database, try to refresh from Shopify
        access_token = get_access_token_for_shop(shop)
        if not access_token:
            return JSONResponse({"error": "Shop not authorized"})
            
        try:
            await ingest_products(shop, access_token)
            products = await get_shop_products(shop)
        except Exception as e:
            print(f"Error refreshing products: {str(e)}")
            return JSONResponse({"error": "Failed to refresh products"})

    if not products:
        return JSONResponse({"recommendations": []})
    
    # Select random products
    pick_count = min(4, len(products))
    chosen = random.sample(products, pick_count)

    recommendations = []
    for p in chosen:
        images = p['images']  # Already parsed from JSON in get_shop_products
        variants = p['variants']  # Already parsed from JSON in get_shop_products
        handle = p['handle']
        
        recommendations.append({
            "title": p['title'],
            "featuredImage": images[0]["src"] if images else "https://via.placeholder.com/400",
            "price": f"${variants[0].get('price', '0.00')}" if variants else "$0.00",
            "variantId": variants[0].get("id", "") if variants else "",
            "onlineStoreUrl": f"/products/{handle}"
        })
    
    return JSONResponse({"recommendations": recommendations})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)