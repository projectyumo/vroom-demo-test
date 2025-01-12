import os
import random
import httpx
import hmac
import json
import hashlib
import base64
from urllib.parse import urlencode, quote
from fastapi import FastAPI, Request, HTTPException, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv, find_dotenv
from db import init_db, store_access_token, get_access_token_for_shop
from typing import Optional
import jwt

load_dotenv(find_dotenv())

SHOPIFY_API_KEY = os.environ.get("SHOPIFY_API_KEY")
SHOPIFY_API_SECRET = os.environ.get("SHOPIFY_API_SECRET")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://admin.shopify.com",
        "https://shopify.com",
        "*myshopify.com"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Add these new functions and routes to your existing FastAPI app

def decode_session_token(token: str) -> Optional[dict]:
    """Decode the JWT session token from Shopify"""
    try:
        decoded = jwt.decode(token, options={"verify_signature": False})
        return decoded
    except jwt.InvalidTokenError:
        return None

@app.get("/")
async def root(request: Request):
    """Handle the initial app load"""
    query_params = dict(request.query_params)
    shop = query_params.get("shop")
    host = query_params.get("host", "")
    
    if not shop:
        raise HTTPException(status_code=400, detail="Missing shop parameter")

    # Check if we have an access token
    access_token = get_access_token_for_shop(shop)
    
    # If no access token, redirect to install
    if not access_token:
        install_url = f"/install?shop={shop}"
        return RedirectResponse(url=install_url)

    # Create HTML response with proper security headers
    html_content = f"""
        <!DOCTYPE html>
        <html>
            <head>
                <title>Shopify App</title>
                <meta charset="utf-8">
                <meta name="viewport" content="width=device-width, initial-scale=1">
                <script src="https://cdn.shopify.com/shopifycloud/app-bridge.js"></script>
            </head>
            <body>
                <div id="app">
                    <h1>App Successfully Installed!</h1>
                    <p>Your app is now ready to use.</p>
                </div>

                <script>
                    if (window.top === window.self) {
                        window.location.href = "https://admin.shopify.com";
                    } else {
                        var config = {{
                            apiKey: '{SHOPIFY_API_KEY}',
                            host: '{host}',
                            forceRedirect: true
                        }};
                        
                        var AppBridge = window['app-bridge'];
                        var createApp = AppBridge.default;
                        var app = createApp(config);
                    }}
                </script>
            </body>
        </html>
    """
    
    response = HTMLResponse(content=html_content)
    
    # Add security headers
    response.headers["Content-Security-Policy"] = "frame-ancestors https://*.shopify.com https://*.myshopify.com;"
    response.headers["X-Frame-Options"] = "ALLOWALL"
    
    return response


# Add this route to handle the client-side redirect
@app.get("/exitframe")
async def exit_frame(request: Request):
    """Handle redirect out of iframe when needed"""
    shop = request.query_params.get("shop")
    host = request.query_params.get("host")
    
    if not shop:
        raise HTTPException(status_code=400, detail="Missing shop parameter")
        
    redirect_url = f"https://{shop}/admin/apps/{SHOPIFY_API_KEY}"
    if host:
        redirect_url = f"https://{host}/apps/{SHOPIFY_API_KEY}"
        
    return RedirectResponse(url=redirect_url)

@app.on_event("startup")
def on_startup():
    print("DEBUG: init_db() being called at startup")
    init_db()


@app.get("/install")
async def install(request: Request):
    """
    Step 1: App installation begins here.
    The merchant clicks install, and we redirect them to Shopify's OAuth screen.
    """
    shop = request.query_params.get("shop")
    if not shop:
        raise HTTPException(status_code=400, detail="Missing shop parameter")

    # Construct the authorization URL
    scopes = "read_products"  # Add more scopes as needed
    redirect_uri = f"{os.environ.get('APP_URL')}/oauth/callback"
    nonce = os.urandom(16).hex()
    
    # Store nonce in your database associated with the shop
    
    install_url = f"https://{shop}/admin/oauth/authorize?" + urlencode({
        'client_id': SHOPIFY_API_KEY,
        'scope': scopes,
        'redirect_uri': redirect_uri,
        'state': nonce,
        'grant_options[]': 'per-user'  # Optional: Remove if you don't need offline access
    })
    
    return RedirectResponse(url=install_url)

@app.get("/oauth/callback")
async def oauth_callback(request: Request):
    """
    Step 2: Handle OAuth callback from Shopify
    """
    # Get query parameters
    shop = request.query_params.get("shop")
    code = request.query_params.get("code")
    state = request.query_params.get("hmac")
    
    if not all([shop, code]):
        raise HTTPException(status_code=400, detail="Missing required parameters")

    # Verify the request is authentic
    if not verify_hmac(dict(request.query_params)):
        raise HTTPException(status_code=400, detail="Invalid HMAC")

    # Exchange temporary code for a permanent access token
    access_token = await get_access_token(shop, code)
    
    # Store the access token securely
    store_access_token(shop, access_token)
    
    # Redirect to app home or configuration page
    app_home_url = f"https://{shop}/admin/apps/{SHOPIFY_API_KEY}"
    return RedirectResponse(url=app_home_url)

async def get_access_token(shop: str, code: str) -> str:
    """
    Exchange temporary code for a permanent access token
    """
    url = f"https://{shop}/admin/oauth/access_token"
    payload = {
        'client_id': SHOPIFY_API_KEY,
        'client_secret': SHOPIFY_API_SECRET,
        'code': code
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload)
        
        if response.status_code != 200:
            raise HTTPException(
                status_code=response.status_code,
                detail=f"Failed to get access token: {response.text}"
            )
        
        data = response.json()
        return data.get('access_token')

def verify_hmac(params: dict) -> bool:
    """
    Verify that the request came from Shopify
    """
    # Remove hmac from params if it exists
    hmac_value = params.pop('hmac', None)
    if not hmac_value:
        return False
    
    # Sort params and convert to query string
    sorted_params = []
    for key in sorted(params.keys()):
        # Replace all instances of '&' and '%' with their encoded versions
        key = str(key)
        value = str(params[key])
        sorted_params.append(f"{key}={value}")
    query = "&".join(sorted_params)
    
    # Calculate hmac using app secret
    digest = hmac.new(
        SHOPIFY_API_SECRET.encode('utf-8'),
        query.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    
    return hmac.compare_digest(digest, hmac_value)

# Optional: Middleware to verify app proxy requests
@app.middleware("http")
async def verify_app_proxy_request(request: Request, call_next):
    """
    Verify that app proxy requests are authentic
    """
    if request.url.path == "/random-products":  # Your app proxy path
        query_dict = dict(request.query_params)
        
        # Get the signature and remove it from params
        signature = query_dict.pop("signature", None)
        timestamp = query_dict.get("timestamp", None)
        
        if not all([signature, timestamp]):
            raise HTTPException(status_code=400, detail="Missing signature or timestamp")
        
        # Sort remaining params alphabetically
        sorted_params = []
        for key in sorted(query_dict.keys()):
            sorted_params.append(f"{key}={query_dict[key]}")
        
        # Join all params with '&'
        query_string = "&".join(sorted_params)
        
        # Calculate HMAC
        computed_signature = hmac.new(
            SHOPIFY_API_SECRET.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        # Compare signatures
        if not hmac.compare_digest(computed_signature, signature):
            raise HTTPException(status_code=400, detail="Invalid signature")
    
    response = await call_next(request)
    return response


# ----------------------------------------
# 3) App Proxy Endpoint: /random-products
# ----------------------------------------
@app.get("/random-products")
async def random_products(request: Request):
    """
    Called by the Shopify app proxy:
    GET https://{shop}.myshopify.com/apps/random-products -> forward to -> /random-products?shop={shop}
    """
    shop = request.query_params.get("shop")
    if not shop:
        return {"error": "No 'shop' query param provided"}

    access_token = get_access_token_for_shop(shop)
    if not access_token:
        return {"error": f"No access token found for shop {shop}."}

    admin_api_url = f"https://{shop}/admin/api/2023-07/products.json"
    headers = {
        "X-Shopify-Access-Token": access_token,
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient() as client:
        r = await client.get(admin_api_url, headers=headers)
        if r.status_code != 200:
            return {"error": f"Failed to fetch products: {r.text}"}
        data = r.json()

    products = data.get("products", [])
    if not products:
        return {"recommendations": []}
    
    pick_count = min(4, len(products))
    chosen = random.sample(products, pick_count)

    recommendations = []
    for p in chosen:
        images = p.get("images", [])
        variants = p.get("variants", [])
        handle = p.get("handle", "")
        image_url = images[0]["src"] if images else "https://via.placeholder.com/400"
        first_variant = variants[0] if variants else {}
        variant_id = first_variant.get("id", "")
        price = first_variant.get("price", "0.00")

        recommendations.append({
            "title": p.get("title", "Untitled"),
            "featuredImage": image_url,
            "price": f"${price}",
            "variantId": variant_id,
            "onlineStoreUrl": f"/products/{handle}"
        })
    
    return {"recommendations": recommendations}


# If running locally (not needed on Railway if you set start command)
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
