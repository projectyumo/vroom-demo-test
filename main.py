import os
import random
import httpx
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

# Pydantic model for 'try-on' request data
class TryOnRequest(BaseModel):
    variantId: str
    productId: Optional[str] = None

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
    """Step 1: Start OAuth by redirecting to Shopify's OAuth screen."""
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

    print(f"Redirecting to Shopify OAuth: {install_url}")
    return RedirectResponse(url=install_url)

@app.get("/callback")
async def callback(request: Request, background_tasks: BackgroundTasks):
    """Handle Shopify OAuth callback. Store token, fetch products."""
    shop = request.query_params.get("shop")
    code = request.query_params.get("code")
    host = request.query_params.get("host")

    if not shop or not code:
        raise HTTPException(status_code=400, detail="Missing required parameters")

    try:
        access_token = await get_access_token(shop, code)
        store_access_token(shop, access_token)

        # Kick off a background fetch of products
        background_tasks.add_task(background_fetch_products, shop, access_token)

        # Redirect back to the Shopify admin
        if host:
            redirect_url = f"https://{host}/apps/{SHOPIFY_API_KEY}"
        else:
            redirect_url = f"https://{shop}/admin/apps/{SHOPIFY_API_KEY}"

        return RedirectResponse(url=redirect_url, status_code=302)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

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
        data = response.json()
        return data.get('access_token')

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
            page_products = data.get("products", [])
            all_products.extend(page_products)

            link_header = response.headers.get("Link", "")
            if 'rel="next"' not in link_header:
                break
            # Grab next page_info
            page_info = link_header.split("page_info=")[1].split(">")[0]

    return all_products

# -------------------------------------------------------------
#  The "try-on" logic (also used in /vylist route below)
# -------------------------------------------------------------
@app.get("/try-on")
async def try_on_get(
    request: Request,
    variantId: str,
    productId: Optional[str] = None
):
    """
    Example GET version of try-on if you wanted to test directly.
    Generally, you'll use POST on the /vylist route, but this can exist too.
    """
    shop = request.query_params.get("shop")
    if not shop:
        raise HTTPException(status_code=400, detail="Missing shop parameter")

    try:
        products = await get_shop_products(shop)
        # Find product with matching variant
        product = None
        for p in products:
            for variant in p['variants']:
                if str(variant.get('id', '')) == variantId:
                    product = p
                    break
            if product:
                break

        if not product:
            raise HTTPException(status_code=404, detail="Product not found")

        return JSONResponse({
            "success": True,
            "tryOnImage": "https://.../some-image.png",
            "productDetails": {
                "id": product['product_id'],
                "title": product['title'],
                "image": product['images'][0]['src'] if product['images'] else None,
                "variant": next((v for v in product['variants'] if str(v.get('id','')) == variantId), None)
            }
        })

    except Exception as e:
        print(f"Error processing try-on GET request: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

# -------------------------------------------------------------
#             The main proxy route: /vylist
# -------------------------------------------------------------
@app.api_route("/vylist", methods=["GET", "POST"])
async def vylist(request: Request):
    """
    This single route is configured as the 'App Proxy' endpoint in Shopify:
    https://<your-shop>.myshopify.com/apps/<proxy-handle>?shop=<shop>&path_prefix=/apps/<endpoint>

    The 'shop' parameter is auto-injected by Shopify. 
    The 'path_prefix' we decode to figure out which logic to run (random-products, try-on, etc.).
    """
    shop = request.query_params.get("shop")
    path_prefix = request.query_params.get("path_prefix")

    if not shop:
        return JSONResponse({"error": "Missing shop parameter"})

    print(f"[vylist] shop={shop}, path_prefix={path_prefix}")

    if path_prefix:
        # Remove '/apps/' from the beginning if it exists
        endpoint = path_prefix.replace('/apps/', '')
        print("TEST!", endpoint)
        if endpoint == 'random-products':
            return await random_products(request)
        
        elif endpoint == 'try-on':
            # We expect a POST with JSON body: { "productId": "...", "variantId": "..." }
            try:
                print("TEST!")
                print(f"TEST! {request}")
                body = await request.json()
                print(f"TEST! {body}")
                try_on_data = TryOnRequest(**body)  # Validate via Pydantic
                return await try_on_post(request, try_on_data)
            except Exception as e:
                print(f"Error processing try-on POST: {str(e)}")
                raise HTTPException(status_code=400, detail="Invalid try-on request data")

    # If we reach here, no known endpoint matched
    raise HTTPException(status_code=404, detail="Endpoint not found")

# A dedicated function to handle try-on POST logic
async def try_on_post(request: Request, try_on_data: TryOnRequest):
    """Process the posted try-on data and return an image, etc."""
    shop = request.query_params.get("shop")
    if not shop:
        raise HTTPException(status_code=400, detail="Missing shop parameter")

    variantId = try_on_data.variantId
    productId = try_on_data.productId

    try:
        products = await get_shop_products(shop)
        product = None
        for p in products:
            for variant in p['variants']:
                if str(variant.get('id', '')) == variantId:
                    product = p
                    break
            if product:
                break

        if not product:
            raise HTTPException(status_code=404, detail="Product not found")

        # Return a mock image for demonstration, or do real processing here
        return JSONResponse({
            "success": True,
            "tryOnImage": "https://via.placeholder.com/600x800?text=Try-On+Success",
            "productDetails": {
                "id": product['product_id'],
                "title": product['title'],
                "image": product['images'][0]['src'] if product['images'] else None,
                "variant": next((v for v in product['variants'] if str(v.get('id','')) == variantId), None)
            }
        })

    except Exception as e:
        print(f"Error processing try-on POST request: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

# Example random-products logic
@app.get("/random-products")
async def random_products(request: Request):
    shop = request.query_params.get("shop")
    if not shop:
        return JSONResponse({"error": "Missing shop parameter"})

    try:
        products = await get_shop_products(shop)
    except Exception as e:
        return JSONResponse({"error": "Failed to fetch products from DB"})

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
            "id": p['product_id'],  # or whatever ID you want to pass
            "onlineStoreUrl": f"/products/{handle}"
        })
    return JSONResponse({"recommendations": recommendations})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
