import os
import random
import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv, find_dotenv
from db import init_db, store_access_token, get_access_token_for_shop
from urllib.parse import urlencode

load_dotenv(find_dotenv())

SHOPIFY_API_KEY = os.environ.get("SHOPIFY_API_KEY")
SHOPIFY_API_SECRET = os.environ.get("SHOPIFY_API_SECRET")
APP_URL = os.environ.get("APP_URL")  # Your ngrok URL for testing

app = FastAPI()

# Basic CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://admin.shopify.com", "https://partners.shopify.com"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
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
    
    # If no access token, start oauth flow
    if not access_token:
        return RedirectResponse(url=f"/install?shop={shop}")

    # Return success response
    return JSONResponse({
        "message": "App is installed and authorized",
        "shop": shop
    })

# Update install endpoint to use /callback
@app.get("/install")
async def install(request: Request):
    """Handle app installation"""
    shop = request.query_params.get("shop")
    if not shop:
        return JSONResponse({"error": "Missing shop parameter"})

    # Construct the authorization URL
    scopes = "read_products,write_products"  # Add more scopes as needed
    redirect_uri = f"{APP_URL}/callback"
    
    install_url = f"https://{shop}/admin/oauth/authorize?" + urlencode({
        'client_id': SHOPIFY_API_KEY,
        'scope': scopes,
        'redirect_uri': redirect_uri,
    })
    
    return RedirectResponse(url=install_url)

@app.get("/callback")
async def callback(request: Request):
    """
    OAuth callback endpoint.
    Shopify redirects here after store owner approves installation.
    """
    shop = request.query_params.get("shop")
    code = request.query_params.get("code")
    
    if not all([shop, code]):
        return JSONResponse({"error": "Missing required parameters"})

    # Exchange temporary code for permanent access token
    access_token = await get_access_token(shop, code)
    
    # Store the access token
    store_access_token(shop, access_token)
    
    # Redirect back to Shopify admin
    return RedirectResponse(url=f"https://{shop}/admin/apps/{SHOPIFY_API_KEY}")

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

@app.get("/random-products")
async def random_products(request: Request):
    """Get random products from the store"""
    shop = request.query_params.get("shop")
    if not shop:
        return JSONResponse({"error": "Missing shop parameter"})

    access_token = get_access_token_for_shop(shop)
    if not access_token:
        return JSONResponse({"error": "Shop not authorized"})

    # Fetch products
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
            
        data = response.json()
        products = data.get("products", [])

    if not products:
        return JSONResponse({"recommendations": []})
    
    # Select random products
    pick_count = min(4, len(products))
    chosen = random.sample(products, pick_count)

    recommendations = []
    for p in chosen:
        images = p.get("images", [])
        variants = p.get("variants", [])
        handle = p.get("handle", "")
        
        recommendations.append({
            "title": p.get("title", "Untitled"),
            "featuredImage": images[0]["src"] if images else "https://via.placeholder.com/400",
            "price": f"${variants[0].get('price', '0.00')}" if variants else "$0.00",
            "variantId": variants[0].get("id", "") if variants else "",
            "onlineStoreUrl": f"/products/{handle}"
        })
    
    return JSONResponse({"recommendations": recommendations})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)