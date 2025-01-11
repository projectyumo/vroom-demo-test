from fastapi import FastAPI
import random

app = FastAPI()

@app.get("/random-products")
async def random_products():
    try:
        # 1. Fetch a list of products from Shopify (Admin or Storefront API) 
        #    or use static data as a demonstration:
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

        # 2. Shuffle or randomly pick 4
        random_4 = random.sample(example_products, 4)

        return {"recommendations": random_4}
    except Exception as e:
        print("Failed to get random products:", e)
        return {"error": "Internal server error"}

# If you want to run locally with: `python main.py`
# you can include uvicorn.run here:
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

