from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel
from typing import Optional, Dict, Any
import httpx
from fastapi.security import OAuth2PasswordBearer
from motor.motor_asyncio import AsyncIOMotorClient

router = APIRouter(prefix="/business", tags=["Business"])
NODEJS_API_BASE = "http://localhost:5000/api/v1"  # Update with actual Node.js API URL
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# MongoDB Connection
MONGO_URI = "mongodb://localhost:27017"  # Update with actual MongoDB URI
db_client = AsyncIOMotorClient(MONGO_URI)
db = db_client.get_database("vypar")  # Update with actual database name

# Pydantic Schemas
class BusinessCreate(BaseModel):
    name: str
    phone: str
    address: str
    pincode: str
    state: str
    businessCategory: str
    businessType: str
    gstNumber: Optional[str] = None
    businessDescription: Optional[str] = None

class BusinessUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    pincode: Optional[str] = None
    state: Optional[str] = None
    businessCategory: Optional[str] = None
    businessType: Optional[str] = None
    gstNumber: Optional[str] = None
    businessDescription: Optional[str] = None

# Function to detect intent
def detect_intent(intent: str, data: Dict[str, Any]):
    if intent == "register_business":
        return f"{NODEJS_API_BASE}/dealer/business-register", "PUT", data
    elif intent == "update_business":
        return f"{NODEJS_API_BASE}/dealer/business-update", "PUT", data
    else:
        raise HTTPException(status_code=400, detail=f"Invalid business intent: {intent}")

async def handle_intent(intent: str, data: Dict[str, Any], token: str):
    # Validate required fields for business registration
    if intent == "register_business" and not all(k in data for k in ["name", "phone", "address", "pincode", "state", "businessCategory", "businessType"]):
        raise HTTPException(status_code=400, detail="All required fields must be provided for registering a business")
    
    # For update operations, keep only non-None fields
    if intent == "update_business":
        update_data = {k: v for k, v in data.items() if v is not None}
        data = update_data
    
    # Get API endpoint details
    url, method, payload = detect_intent(intent, data)
    headers = {"Authorization": f"Bearer {token}"}
    
    # Make the API request
    async with httpx.AsyncClient() as client:
        try:
            if method == "POST":
                response = await client.post(url, json=payload, headers=headers)
            elif method == "PUT":
                response = await client.put(url, json=payload, headers=headers)
            else:
                raise HTTPException(status_code=500, detail="Unsupported HTTP method")
            
            # Handle the response
            if response.status_code >= 400:
                error_detail = response.json() if response.headers.get("content-type") == "application/json" else response.text
                raise HTTPException(status_code=response.status_code, detail=error_detail)
            
            return response.json()
        except httpx.RequestError as exc:
            raise HTTPException(status_code=500, detail=f"API request failed: {str(exc)}")
