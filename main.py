import os
import httpx
import random

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv, find_dotenv

from db import init_db, store_access_token, get_access_token_for_shop

load_dotenv(find_dotenv())

SHOPIFY_API_KEY = os.environ.get("SHOPIFY_API_KEY")
SHOPIFY_API_SECRET = os.environ.get("SHOPIFY_API_SECRET")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def on_startup():
    print("DEBUG: init_db() being called at startup")
    init_db()


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    # Possibly read the file from disk, or store it as a string in code
    with open("templates/index.html", "r") as f:
        html_content = f.read()
    return html_content


########################################
# 1) OAuth Callback
########################################
@app.get("/auth/callback")
def auth_callback(shop: str, code: str):
    token_url = f"https://{shop}/admin/oauth/access_token"
    payload = {
        "client_id": SHOPIFY_API_KEY,
        "client_secret": SHOPIFY_API_SECRET,
        "code": code
    }
    resp = httpx.post(token_url, data=payload)
    if resp.status_code != 200:
        return {"error": f"Failed to get token from {shop}: {resp.text}"}
    
    token_data = resp.json()
    access_token = token_data.get("access_token")
    if not access_token:
        return {"error": "No access token returned in response."}
    
    store_access_token(shop, access_token)
    return {"message": f"Shop {shop} installed. Token stored."}


########################################
# 2) App Proxy Endpoint: /random-products
########################################
@app.get("/random-products")
async def random_products(request: Request):
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
