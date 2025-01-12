from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
import shopify
import random
import os
from typing import List, Dict, Any
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

SHOP_URL = os.getenv('SHOP_URL')
ACCESS_TOKEN = os.getenv('SHOPIFY_ACCESS_TOKEN')

app = FastAPI()

# CORS middleware setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Shopify API configuration
SHOP_URL = os.getenv('SHOP_URL', 'your-store.myshopify.com')
ACCESS_TOKEN = os.getenv('SHOPIFY_ACCESS_TOKEN', 'your-access-token')

def init_shopify():
    shop_url = f"https://{ACCESS_TOKEN}:@{SHOP_URL}/admin/api/2024-01"
    shopify.ShopifyResource.set_site(shop_url)

class ProductResponse(BaseModel):
    recommendations: List[Dict[str, Any]]

@app.get("/random-products", response_model=ProductResponse)
async def random_products(request: Request, limit: int = 4):
    try:
        init_shopify()
        
        # Fetch all published products
        products = shopify.Product.find(
            limit=250,  # Adjust based on your store size
            published_status='published'
        )
        
        if not products:
            return {"recommendations": []}

        # Filter for products with variants and images
        valid_products = [
            product for product in products 
            if product.variants and product.images
        ]

        # Select random products
        selected_count = min(limit, len(valid_products))
        random_products = random.sample(valid_products, selected_count)

        # Format the response
        recommendations = []
        for product in random_products:
            # Get the first available variant
            variant = product.variants[0]
            # Get the first image
            image = product.images[0] if product.images else None
            
            recommendations.append({
                "title": product.title,
                "featuredImage": image.src if image else "",
                "price": float(variant.price) if variant else 0.0,
                "variantId": str(variant.id) if variant else "",
                "onlineStoreUrl": f"/products/{product.handle}",
                "compareAtPrice": float(variant.compare_at_price) if variant and variant.compare_at_price else None
            })

        return {"recommendations": recommendations}

    except Exception as e:
        print(f"Error fetching random products: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Failed to fetch random products"
        )

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app", 
        host="0.0.0.0", 
        port=8000, 
        reload=True,
        log_level="info"
    )
