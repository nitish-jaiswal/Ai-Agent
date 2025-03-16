from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr
from typing import Optional, List, Dict, Any
import httpx

router = APIRouter(prefix="/sales", tags=["Sales"])
NODEJS_API_BASE = "http://localhost:5000/api/v1"  # Update with actual Node.js API URL

# Pydantic Schemas
class ProductItem(BaseModel):
    productId: str
    quantity: int
    rate: float
    gstApplied: float

class SaleCreate(BaseModel):
    customerId: str
    products: List[ProductItem]
    paymentMethod: str
    amountPaid: Optional[float] = 0

class InvoiceGenerate(BaseModel):
    saleId: str
    recipientEmail: EmailStr

# Function to detect intent
def detect_intent(intent: str, data: Dict[str, Any]):
    """
    Map sales-related intents to appropriate API endpoints and HTTP methods
    """
    if intent == "create_sale":
        return f"{NODEJS_API_BASE}/sales/buy-product", "POST", data
    
    elif intent == "generate_invoice":
        return f"{NODEJS_API_BASE}/sales/invoices", "POST", data
    
    else:
        raise HTTPException(status_code=400, detail=f"Invalid sales intent: {intent}")

# Generic intent handler
async def handle_intent(intent: str, data: Dict[str, Any]):
    """
    Process sales-related intents with provided data and forward to Node.js API
    """
    # Validate data based on intent
    if intent == "create_sale":
        required_fields = ["customerId", "products", "paymentMethod"]
        if not all(k in data for k in required_fields):
            raise HTTPException(
                status_code=400, 
                detail=f"Missing required fields. Required: {', '.join(required_fields)}"
            )
        
        # Validate products list
        products = data.get("products", [])
        if not isinstance(products, list) or len(products) == 0:
            raise HTTPException(status_code=400, detail="At least one product is required for a sale")
        
        # Check each product has required fields
        for i, product in enumerate(products):
            if not all(k in product for k in ["productId", "quantity", "rate", "gstApplied"]):
                raise HTTPException(
                    status_code=400, 
                    detail=f"Product at index {i} is missing required fields"
                )
    
    elif intent == "generate_invoice":
        if not all(k in data for k in ["saleId", "recipientEmail"]):
            raise HTTPException(
                status_code=400, 
                detail="saleId and recipientEmail are required for generating an invoice"
            )
    
    # Get URL, method, and payload for the intent
    url, method, payload = detect_intent(intent, data)
    
    # Make the API request
    async with httpx.AsyncClient() as client:
        try:
            if method == "POST":
                response = await client.post(url, json=payload)
            elif method == "PUT":
                response = await client.put(url, json=payload)
            elif method == "GET":
                response = await client.get(url)
            else:
                raise HTTPException(status_code=500, detail="Unsupported HTTP method")
            
            # Check for errors in the response
            if response.status_code >= 400:
                error_detail = response.json() if response.headers.get("content-type") == "application/json" else response.text
                raise HTTPException(status_code=response.status_code, detail=error_detail)
            
            # Return the response data
            return response.json()
            
        except httpx.RequestError as exc:
            raise HTTPException(status_code=500, detail=f"API request failed: {str(exc)}")