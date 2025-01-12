import os
import httpx
import random

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv, find_dotenv

from db import init_db, store_access_token, get_access_token_for_shop

load_dotenv(find_dotenv())

# Read your Shopify API creds from environment
SHOPIFY_API_KEY = os.environ.get("SHOPIFY_API_KEY")
SHOPIFY_API_SECRET = os.environ.get("SHOPIFY_API_SECRET")

app = FastAPI()

# CORS middleware setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def on_startup():
    # Initialize DB table on server start
    init_db()


########################################
# 1) OAuth Callback
########################################
@app.get("/auth/callback")
def auth_callback(shop: str, code: str):
    """
    Shopify redirects here after the merchant approves the app.
    We exchange the 'code' for an access token, store it in Postgres.
    """
    # 1. Request the permanent access token using the code & your API secrets
    token_url = f"https://{shop}/admin/oauth/access_token"
    payload = {
        "client_id": SHOPIFY_API_KEY,
        "client_secret": SHOPIFY_API_SECRET,
        "code": code
    }

    # You can use 'requests' or 'httpx'
    resp = httpx.post(token_url, data=payload)
    if resp.status_code != 200:
        return {"error": f"Failed to get token from {shop}: {resp.text}"}
    
    token_data = resp.json()
    access_token = token_data.get("access_token")
    if not access_token:
        return {"error": "No access token returned in response."}
    
    # 2. Store the token in the DB
    store_access_token(shop, access_token)

    # 3. Return or redirect merchant to your app's UI
    return {"message": f"Shop {shop} installed. Token stored."}

@app.get("/install")
def install(shop: str):
    """
    The merchant visits /install?shop=example-store.myshopify.com
    We redirect them to Shopify's oauth/authorize page, which triggers the OAuth flow.
    """
    # Build the OAuth authorize URL
    # e.g., https://{shop}/admin/oauth/authorize
    #       ?client_id=YOUR_SHOPIFY_API_KEY
    #       &scope=desired_scopes
    #       &redirect_uri=https://yourapp.com/auth/callback
    # Possibly you have more scopes or a state parameter:
    client_id = SHOPIFY_API_KEY  # from your env
    scopes = "read_products"     # or "read_products,write_products" etc.
    redirect_uri = "https://yourapp.up.railway.app/auth/callback"

    # Construct the final URL
    authorize_url = (
        f"https://{shop}/admin/oauth/authorize"
        f"?client_id={client_id}"
        f"&scope={scopes}"
        f"&redirect_uri={redirect_uri}"
    )

    # Redirect the user to Shopify's install prompt
    return RedirectResponse(authorize_url)

########################################
# 2) App Proxy Endpoint: /random-products
########################################
@app.get("/random-products")
async def random_products(request: Request):
    """
    Called by Shopify's app proxy at:
    https://{shop}.myshopify.com/apps/random-products
    => forwards to:
    https://yourapp.up.railway.app/random-products?shop={shop}
    """
    shop = request.query_params.get("shop")
    if not shop:
        return {"error": "No 'shop' query param provided"}

    access_token = get_access_token_for_shop(shop)
    if not access_token:
        return {"error": f"No access token found for shop {shop}."}
    
    # Call the Shopify Admin API to fetch products
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
    
    # Randomly pick up to 4
    pick_count = min(4, len(products))
    chosen = random.sample(products, pick_count)

    # Transform them for the storefront JS
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


# Local dev: uvicorn main:app --reload --port 8000
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

