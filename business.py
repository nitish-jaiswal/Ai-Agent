import os
import jwt
from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel
from typing import Optional, Dict, Any
import httpx
from fastapi.security import OAuth2PasswordBearer
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId

router = APIRouter(prefix="/business", tags=["Business"])
NODEJS_API_BASE = "https://verce-ankurs-projects-b664b274.vercel.app/api/v1"  # Update with your Node.js API URL
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# MongoDB Connection (if needed for other operations)
MONGO_URI = "mongodb+srv://projectvaypar:Ankur@cluster0.vppsc.mongodb.net/"  # Update with your MongoDB URI
db_client = AsyncIOMotorClient(MONGO_URI)
db = db_client.get_database("test")  # Update with your database name

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
    # businessId is not required from the client; it will be obtained from the token.
    name: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    pincode: Optional[str] = None
    state: Optional[str] = None
    businessCategory: Optional[str] = None
    businessType: Optional[str] = None
    gstNumber: Optional[str] = None
    businessDescription: Optional[str] = None

# Use PyJWT to decode the token and extract the dealer id.
def get_dealer_id(token: str) -> str:
    secret_key = os.getenv("JWT_SECRET")
    if not secret_key:
        raise HTTPException(status_code=500, detail="JWT secret key not set in environment")
    try:
        payload = jwt.decode(token, secret_key, algorithms=["HS256"])
        # Use "dealer_id" if available, otherwise fallback to "_id"
        dealer_id = payload.get("dealer_id") or payload.get("_id")
        if not dealer_id or not ObjectId.is_valid(dealer_id):
            raise HTTPException(status_code=400, detail="Invalid dealer id in token")
        return dealer_id
    except Exception as e:
        raise HTTPException(status_code=400, detail="Invalid token format")

# Function to detect intent for only register and update
def detect_intent(intent: str, data: Dict[str, Any]):
    if intent == "register_business":
        return f"{NODEJS_API_BASE}/dealer/business-register", "PUT", data
    elif intent == "update_business":
        return f"{NODEJS_API_BASE}/dealer/business-update", "PUT", data
    else:
        raise HTTPException(status_code=400, detail=f"Invalid business intent: {intent}")

async def handle_intent(intent: str, data: Dict[str, Any], token: str):
    # Extract dealer id from token using our helper
    dealer_id = get_dealer_id(token)
    data["dealer"] = dealer_id

    if intent == "register_business":
        # Validate required fields for registration
        required_fields = ["name", "phone", "address", "pincode", "state", "businessCategory", "businessType"]
        missing = [field for field in required_fields if field not in data or not data[field]]
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"Missing required fields for registering a business: {', '.join(missing)}"
            )
    elif intent == "update_business":
        # Instead of querying the DB for a dealer record, use the dealer id directly.
        # Use dealer_id as businessId.
        data["businessId"] = dealer_id
        # Keep only fields with non-None values (excluding dealer and businessId)
        update_data = {k: v for k, v in data.items() if k not in {"dealer", "businessId"} and v is not None}
        if not update_data:
            raise HTTPException(status_code=400, detail="At least one field to update must be provided")
        # Merge back dealer and businessId into the payload.
        update_data["dealer"] = dealer_id
        update_data["businessId"] = dealer_id
        data = update_data

    url, method, payload = detect_intent(intent, data)
    headers = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient() as client:
        try:
            if method == "POST":
                response = await client.post(url, json=payload, headers=headers)
            elif method == "PUT":
                response = await client.put(url, json=payload, headers=headers)
            else:
                raise HTTPException(status_code=500, detail="Unsupported HTTP method")
            
            if response.status_code >= 400:
                error_detail = (
                    response.json()
                    if response.headers.get("content-type") == "application/json"
                    else response.text
                )
                raise HTTPException(status_code=response.status_code, detail=error_detail)
            
            return response.json()
        except httpx.RequestError as exc:
            raise HTTPException(status_code=500, detail=f"API request failed: {str(exc)}")
