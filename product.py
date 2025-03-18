from fastapi import APIRouter, HTTPException, Depends, Body
from pydantic import BaseModel
from typing import Optional, Dict, Any
import httpx
import json
import os
import re
from fastapi.security import OAuth2PasswordBearer
from motor.motor_asyncio import AsyncIOMotorClient  # New import for MongoDB
from bson.json_util import dumps  # Import this at the top of your file
import json

router = APIRouter(prefix="/products", tags=["Products"])
NODEJS_API_BASE = "https://verce-ankurs-projects-b664b274.vercel.app/api/v1"
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# Set up MongoDB connection (similar to customer.py)
MONGO_URI = os.getenv("MONGO_URI", "mongodb+srv://projectvaypar:Ankur@cluster0.vppsc.mongodb.net/")
db_client = AsyncIOMotorClient(MONGO_URI)
db = db_client.get_database("test")

# Pydantic Schemas for Products
class ProductCreate(BaseModel):
    name: str
    rate: float
    gstRate: float
    dealer: str  # This field is required per the backend schema

class ProductUpdate(BaseModel):
    productId: str  # <-- Added required productId field
    name: Optional[str] = None
    rate: Optional[float] = None
    gstRate: Optional[float] = None
    dealer: Optional[str] = None

class ProductDelete(BaseModel):
    name: str

class NLPQuery(BaseModel):
    user_query: str

# Helper function to fetch product by name directly from MongoDB


# Helper function to fetch product by name directly from MongoDB and serialize ObjectId
async def get_product_by_name_db(name: str):
    product = await db.products.find_one({"name": {"$regex": f"^{name}$", "$options": "i"}})
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    # Convert the product document to a JSON-friendly dict using bson.json_util.dumps
    product_json = json.loads(dumps(product))
    return product_json


def detect_product_intent(intent: str, data: Dict[str, Any]):
    if intent == "create_product":
        return f"{NODEJS_API_BASE}/product/create-product", "POST", data
    elif intent == "update_product":
        return f"{NODEJS_API_BASE}/product/update-product", "PUT", data
    elif intent == "delete_product":
        return f"{NODEJS_API_BASE}/product/delete-product", "DELETE", data
    elif intent == "get_product_by_name":
        # For getting product details via remote API, the backend expects "productName"
        payload = {"productName": data.get("name")}
        return f"{NODEJS_API_BASE}/product/get-by-name", "GET", payload
    elif intent == "get_all_products":
        # New intent to get all products for the dealer (dealer id is provided via JWT in the header)
        return f"{NODEJS_API_BASE}/product/product-of-dealer", "GET", {}
    else:
        raise HTTPException(status_code=400, detail=f"Invalid product intent: {intent}")

async def handle_product_intent(intent: str, data: Dict[str, Any], token: str):
    # For get_product_by_name, fetch directly from the DB
    if intent == "get_product_by_name":
        product = await get_product_by_name_db(data.get("name"))
        return {"status": "success", "data": product}
    
    # Handle update_product explicitly
    if intent == "update_product":
        # Validate that productId is provided
        if "productId" not in data or not data["productId"]:
            raise HTTPException(status_code=400, detail="Missing productId")
        
        # Build payload with only the fields expected by the backend.
        # Note: Ensure productId is a string (a valid ObjectId in string form).
        payload = {"productId": str(data["productId"])}
        
        # Include update fields if provided
        if "name" in data and data["name"]:
            payload["name"] = data["name"]
        if "rate" in data and data["rate"]:
            try:
                payload["rate"] = float(data["rate"])
            except Exception:
                raise HTTPException(status_code=400, detail="Invalid rate value")
        if "gstRate" in data and data["gstRate"]:
            try:
                payload["gstRate"] = float(data["gstRate"])
            except Exception:
                raise HTTPException(status_code=400, detail="Invalid gstRate value")
        
        # Ensure at least one update field is provided besides productId
        if len(payload) == 1:
            raise HTTPException(
                status_code=400,
                detail="At least one update field (name, rate, or gstRate) must be provided"
            )
        
        # Use the update URL and HTTP method
        url = f"{NODEJS_API_BASE}/product/update-product"
        method = "PUT"
    
    else:
        url, method, payload = detect_product_intent(intent, data)
    
    headers = {"Authorization": f"Bearer {token}"}
    
    # (Optional) Debug print – remove or disable in production
    print("Update payload:", payload)
    
    async with httpx.AsyncClient() as client:
        try:
            if method == "POST":
                response = await client.post(url, json=payload, headers=headers)
            elif method == "PUT":
                response = await client.put(url, json=payload, headers=headers)
            elif method == "DELETE":
                response = await client.request("DELETE", url, json=payload, headers=headers)
            elif method == "GET":
                response = await client.get(url, params=payload, headers=headers)
            else:
                raise HTTPException(status_code=500, detail="Unsupported HTTP method")
            
            if response.status_code >= 400:
                try:
                    error_detail = response.json()
                except Exception:
                    error_detail = response.text
                return {
                    "status": "error",
                    "message": error_detail if isinstance(error_detail, str) else json.dumps(error_detail)
                }
            
            result = response.json()
            result["status"] = "success"
            return result
        except httpx.RequestError as exc:
            return {
                "status": "error",
                "message": f"API request failed: {str(exc)}"
            }

    # For get_product_by_name, fetch directly from the DB
    if intent == "get_product_by_name":
        product = await get_product_by_name_db(data.get("name"))
        return {"status": "success", "data": product}
    
    # Explicitly build payload for update_product intent
    if intent == "update_product":
        payload = {}
        
        # Validate and convert productId
        if "productId" not in data or not data["productId"]:
            raise HTTPException(status_code=400, detail="Missing productId")
        payload["productId"] = str(data["productId"])
        
        # Process optional update fields
        if "name" in data and data["name"]:
            payload["name"] = data["name"]
        
        if "rate" in data and data["rate"]:
            try:
                payload["rate"] = float(data["rate"])
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid rate value")
        
        if "gstRate" in data and data["gstRate"]:
            try:
                payload["gstRate"] = float(data["gstRate"])
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid gstRate value")
        
        # Ensure at least one field to update is provided besides productId
        if len(payload) == 1:
            raise HTTPException(
                status_code=400,
                detail="At least one field (name, rate, or gstRate) must be provided to update"
            )
        
        url = f"{NODEJS_API_BASE}/product/update-product"
        method = "PUT"
    else:
        # For other intents, use the detect_product_intent function
        url, method, payload = detect_product_intent(intent, data)
    
    headers = {"Authorization": f"Bearer {token}"}
    
    async with httpx.AsyncClient() as client:
        try:
            if method == "POST":
                response = await client.post(url, json=payload, headers=headers)
            elif method == "PUT":
                response = await client.put(url, json=payload, headers=headers)
            elif method == "DELETE":
                if payload:
                    response = await client.request("DELETE", url, json=payload, headers=headers)
                else:
                    response = await client.delete(url, headers=headers)
            elif method == "GET":
                response = await client.get(url, params=payload, headers=headers)
            else:
                raise HTTPException(status_code=500, detail="Unsupported HTTP method")
            
            if response.status_code >= 400:
                # Return the error detail from the backend response
                error_detail = (
                    response.json() 
                    if response.headers.get("content-type") == "application/json" 
                    else response.text
                )
                return {
                    "status": "error",
                    "message": error_detail if isinstance(error_detail, str) else json.dumps(error_detail)
                }
            
            result = response.json()
            result["status"] = "success"
            return result
        except httpx.RequestError as exc:
            return {
                "status": "error",
                "message": f"API request failed: {str(exc)}"
            }


# Function to extract product name from NLP query
def extract_product_name(user_query: str) -> str:
    # Look for patterns like "product name X" or "name X"
    product_name_match = re.search(r"(?:product name|name)\s+(\w+)", user_query.lower())
    
    if product_name_match:
        # Return the captured product name
        return product_name_match.group(1)
    
    # If no match, try other patterns
    words = user_query.split()
    # Assume the last word might be the product name if it follows "product" or similar terms
    if len(words) >= 2 and any(term in words for term in ["product", "details", "get"]):
        return words[-1]
    
    # Default fallback
    raise HTTPException(status_code=400, detail="Could not extract product name from query")

# Endpoint to create a new product
@router.post("/create", summary="Create a new product")
async def create_product(product: ProductCreate, token: str = Depends(oauth2_scheme)):
    data = product.dict()
    result = await handle_product_intent("create_product", data, token)
    if result.get("status") != "success":
        raise HTTPException(status_code=400, detail=result.get("message"))
    return {
        "statusCode": 200,
        "data": result.get("data", result),
        "message": "Product created successfully",
        "success": True,
        "status": "success"
    }

# Endpoint to update an existing product
@router.put("/update", summary="Update an existing product")
async def update_product(product: ProductUpdate, token: str = Depends(oauth2_scheme)):
    data = product.dict()
    result = await handle_product_intent("update_product", data, token)
    if result.get("status") != "success":
        raise HTTPException(status_code=400, detail=result.get("message"))
    return {
        "statusCode": 200,
        "data": result.get("data", result),
        "message": "Product updated successfully",
        "success": True,
        "status": "success"
    }

# Endpoint to delete a product by name
@router.delete("/delete/by-name", summary="Delete a product by name")
async def delete_product(product: ProductDelete, token: str = Depends(oauth2_scheme)):
    data = product.dict()
    result = await handle_product_intent("delete_product", data, token)
    if result.get("status") != "success":
        raise HTTPException(status_code=400, detail=result.get("message"))
    return {
        "statusCode": 200,
        "data": result.get("data", result),
        "message": "Product deleted successfully",
        "success": True,
        "status": "success"
    }

# Endpoint to get product details by name (uses the modified handle_product_intent with DB fetch)
@router.get("/get-by-name", summary="Get product details by name")
async def get_product_by_name(name: str, token: str = Depends(oauth2_scheme)):
    data = {"name": name}
    result = await handle_product_intent("get_product_by_name", data, token)
    if result.get("status") != "success":
        raise HTTPException(status_code=400, detail=result.get("message"))
    return {
        "statusCode": 200,
        "data": result.get("data", result),
        "message": "Product fetched successfully",
        "success": True,
        "status": "success"
    }

# NEW ENDPOINT: NLP interface for product queries
@router.post("/nlp-query", summary="Process natural language product queries")
async def process_nlp_query(query: NLPQuery, token: str = Depends(oauth2_scheme)):
    user_query = query.user_query.lower()
    
    # Detect intent type from query
    if "get" in user_query and ("product" in user_query or "details" in user_query):
        # Extract product name from the query
        product_name = extract_product_name(user_query)
        
        # Pass the extracted name to the get_product_by_name intent
        data = {"name": product_name}
        result = await handle_product_intent("get_product_by_name", data, token)
        
        if result.get("status") != "success":
            return {
                "status": "error",
                "message": result.get("message"),
                "conversation_id": result.get("conversation_id", "")
            }
        
        return {
            "statusCode": 200,
            "data": result.get("data", result),
            "message": f"Product '{product_name}' fetched successfully",
            "success": True,
            "status": "success",
            "conversation_id": result.get("conversation_id", "")
        }
    
    # Add other intent types (create, update, delete) as needed
    
    # Default response for unrecognized intent
    return {
        "status": "error",
        "message": "Could not determine intent from query",
        "conversation_id": ""
    }

# Attach the intent handling function to the router so it can be accessed externally (e.g., from main.py)
router.handle_intent = handle_product_intent
