from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import random

app = FastAPI()

# If you only want to allow your specific store domain:
# origins = ["https://vylist-test-store.myshopify.com"]
# If you are okay with any domain (less secure):
origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/random-products")
async def random_products():
    try:
        example_products = [
            {
                "title": "Random Product A",
                "featuredImage": "https://via.placeholder.com/400?text=Prod+A",
                "price": "$19.99",
                "variantId": "1234567890",
                "onlineStoreUrl": "/products/product-a"
            },
            {
                "title": "Random Product B",
                "featuredImage": "https://via.placeholder.com/400?text=Prod+B",
                "price": "$24.99",
                "variantId": "9876543210",
                "onlineStoreUrl": "/products/product-b"
            },
            {
                "title": "Random Product C",
                "featuredImage": "https://via.placeholder.com/400?text=Prod+C",
                "price": "$14.99",
                "variantId": "5555555555",
                "onlineStoreUrl": "/products/product-c"
            },
            {
                "title": "Random Product D",
                "featuredImage": "https://via.placeholder.com/400?text=Prod+D",
                "price": "$29.99",
                "variantId": "6666666666",
                "onlineStoreUrl": "/products/product-d"
            },
            {
                "title": "Random Product E",
                "featuredImage": "https://via.placeholder.com/400?text=Prod+E",
                "price": "$9.99",
                "variantId": "7777777777",
                "onlineStoreUrl": "/products/product-e"
            }
        ]

        random_4 = random.sample(example_products, 4)
        return {"recommendations": random_4}
    except Exception as e:
        print("Failed to get random products:", e)
        return {"error": "Internal server error"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

