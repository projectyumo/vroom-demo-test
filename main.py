import os
import random
import httpx
import json

import firebase_admin
from firebase_admin import credentials, db, firestore, storage

from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse, RedirectResponse

from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv, find_dotenv
from db import init_db, store_access_token, get_access_token_for_shop, store_product, get_shop_products
from urllib.parse import urlencode
from pydantic import BaseModel
from typing import Optional

load_dotenv(find_dotenv())

SHOPIFY_API_KEY = os.environ.get("SHOPIFY_API_KEY")
SHOPIFY_API_SECRET = os.environ.get("SHOPIFY_API_SECRET")
APP_URL = os.environ.get("APP_URL")
FIREBASE_ID = os.environ.get("FIREBASE_ID")
FIREBASE_URL = os.environ.get("FIREBASE_URL")
FIREBASE_CREDENTIALS = {
                          "type": os.environ.get("FIREBASE_TYPE"),
                          "project_id": os.environ.get("FIREBASE_PROJECT_ID"),
                          "private_key_id": os.environ.get("FIREBASE_PRIVATE_KEY_ID"),
                          "private_key": os.environ.get("FIREBASE_PRIVATE_KEY").replace("\\n", "\n"),
                          "client_email": os.environ.get("FIREBASE_CLIENT_EMAIL"),
                          "client_id": os.environ.get("FIREBASE_CLIENT_ID"),
                          "auth_uri": os.environ.get("FIREBASE_AUTH_URI"),
                          "token_uri": os.environ.get("FIREBASE_TOKEN_URI"),
                          "auth_provider_x509_cert_url": os.environ.get("FIREBASE_AUTH_PROVIDER"),
                          "client_x509_cert_url": os.environ.get("FIREBASE_CLIENT_X509"),
                          "universe_domain": os.environ.get("FIREBASE_UNIVERSE_DOMAIN")
                        }

# Define hats, tops, and bottoms

PRODUCT_TYPE_MAP = {
                    "baseball_hat": "headwear",
                    "hoodie": "tops",
                    "t_shirt": "tops",
                    "sweater": "tops",
                    "pants": "bottoms",
                    "training_shorts": "bottoms",
                    "big_shorts": "bottoms",
                    "jordan_4": "shoes",
                    "air_force_1_low": "shoes"
                   }
    
# # TODO: MOVE TO ENVIRONMENTAL VARIABLE
# PRODUCT_TYPE_MAP = json.load(open('./maps/product_type_map.json'))
cred = credentials.Certificate(FIREBASE_CREDENTIALS)
firebase_admin.initialize_app(cred)

db = firestore.client()
products_ref = products_ref = db.collection('products_v4')
    
bucket = storage.bucket(FIREBASE_URL) 
blobs = list(bucket.list_blobs(prefix=f"{FIREBASE_ID}/tmp/", max_results=100))

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

# Pydantic models
class TryOnRequest(BaseModel):
    variantId: str
    productId: Optional[str] = None
    productHandle: str

# Installation and auth endpoints
@app.get("/")
async def root(request: Request):
    """Check if app is installed, otherwise redirect to /install."""
    shop = request.query_params.get("shop")
    if not shop:
        return JSONResponse({"error": "Missing shop parameter"})

    access_token = get_access_token_for_shop(shop)
    if not access_token:
        return RedirectResponse(url=f"/install?shop={shop}")

    return JSONResponse({
        "status": "success",
        "message": "App is installed and authorized",
        "shop": shop
    })

@app.get("/install")
async def install(request: Request):
    """Start OAuth by redirecting to Shopify's OAuth screen."""
    shop = request.query_params.get("shop")
    if not shop:
        raise HTTPException(status_code=400, detail="Missing shop parameter")

    scopes = "read_products"
    redirect_uri = f"{APP_URL}/callback"

    install_url = f"https://{shop}/admin/oauth/authorize?" + urlencode({
        'client_id': SHOPIFY_API_KEY,
        'scope': scopes,
        'redirect_uri': redirect_uri,
    })

    return RedirectResponse(url=install_url)

@app.get("/callback")
async def callback(request: Request, background_tasks: BackgroundTasks):
    """Handle Shopify OAuth callback."""
    shop = request.query_params.get("shop")
    code = request.query_params.get("code")
    host = request.query_params.get("host")

    if not shop or not code:
        raise HTTPException(status_code=400, detail="Missing required parameters")

    try:
        access_token = await get_access_token(shop, code)
        store_access_token(shop, access_token)
        background_tasks.add_task(background_fetch_products, shop, access_token)

        redirect_url = f"https://{host}/apps/{SHOPIFY_API_KEY}" if host else f"https://{shop}/admin/apps/{SHOPIFY_API_KEY}"
        return RedirectResponse(url=redirect_url, status_code=302)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Helper functions
async def get_access_token(shop: str, code: str) -> str:
    """Exchange temporary code for permanent access token."""
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
            raise HTTPException(status_code=response.status_code, detail=response.text)
        return response.json().get('access_token')

async def background_fetch_products(shop: str, access_token: str):
    """Background task to fetch all products and store in DB."""
    try:
        products = await fetch_all_products(shop, access_token)
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
        print(f"Successfully stored products for {shop}.")
    except Exception as e:
        print(f"Error in background product fetch for {shop}: {str(e)}")

async def fetch_all_products(shop: str, access_token: str) -> list:
    """Pull products from Shopify (with pagination)."""
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
            response = await client.get(url, headers=headers)
            if response.status_code != 200:
                raise HTTPException(status_code=response.status_code, detail=response.text)

            data = response.json()
            all_products.extend(data.get("products", []))

            link_header = response.headers.get("Link", "")
            if 'rel="next"' not in link_header:
                break
            page_info = link_header.split("page_info=")[1].split(">")[0]

    return all_products

# Main vylist routes
@app.post("/vylist/try-on")
async def try_on(request: Request, try_on_data: TryOnRequest):
    """Handle try-on requests."""
    shop = request.query_params.get("shop")
    print("TEST")
    print(try_on_data)
    product_handle = try_on_data.productHandle
    #TODO: current_outfit = request.query_params.get("currentOutfitUrl")
    customer_id = request.headers.get("X-Shopify-Customer-Id")
    session_token = request.headers.get("X-Shopify-Session")
    
    product_url = f"https://{shop}/products/{product_handle}.json"
    # FIREBASE QUERY FOR PRODUCT JSON
    docs = products_ref.where('main_product_url', '==', product_url).limit(2).stream()
    doc = next(docs, None).to_dict()
    product_id = doc['image_url'].split('/')[-1]
    product_category = PRODUCT_TYPE_MAP[doc['product_type']]
    print(product_url, product_id, product_category)
    if product_category == "headwear":
        pass
    elif product_category == "tops":
        pass
    elif product_category == "bottoms":
        pass
    elif product_category == "shoes":
        pass
    
    
    print(f"Customer ID: {customer_id}, Session Token: {session_token}")
    if not shop:
        raise HTTPException(status_code=400, detail="Missing shop parameter")

    try:
        products = await get_shop_products(shop)
        product = None
        for p in products:
            for variant in p['variants']:
                if str(variant.get('id', '')) == try_on_data.variantId:
                    product = p
                    break
            if product:
                break

        if not product:
            raise HTTPException(status_code=404, detail="Product not found")

        return JSONResponse({
            "success": True,
            "tryOnImage": f"https://storage.googleapis.com/{FIREBASE_URL}/" + random.choice(blobs).name,
            "productDetails": {
                "id": product['product_id'],
                "title": product['title'],
                "image": product['images'][0]['src'] if product['images'] else None,
                "variant": next((v for v in product['variants'] if str(v.get('id','')) == try_on_data.variantId), None)
            }
        })

    except Exception as e:
        print(f"Error processing try-on request: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/vylist/random-products")
async def random_products(request: Request):
    """Get random product recommendations."""
    shop = request.query_params.get("shop")
    if not shop:
        return JSONResponse({"error": "Missing shop parameter"})

    try:
        products = await get_shop_products(shop)
        if not products:
            return JSONResponse({"recommendations": []})

        pick_count = min(4, len(products))
        chosen = random.sample(products, pick_count)

        recommendations = []
        for p in chosen:
            images = p.get('images', [])
            variants = p.get('variants', [])
            handle = p.get('handle', '')
      
            recommendations.append({
                "title": p['title'],
                "featuredImage": images[0]["src"] if images else "https://via.placeholder.com/400",
                "price": f"${variants[0].get('price', '0.00')}" if variants else "$0.00",
                "variantId": variants[0].get("id", "") if variants else "",
                "productHandle": handle,
                "id": p['product_id'],
                "onlineStoreUrl": f"/products/{handle}"
            })
        return JSONResponse({"recommendations": recommendations})

    except Exception as e:
        print(f"Error fetching random products: {str(e)}")
        return JSONResponse({"error": "Failed to fetch products"})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)