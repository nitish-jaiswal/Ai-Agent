from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, EmailStr
from typing import Optional, Dict, Any
import httpx
from fastapi.security import OAuth2PasswordBearer
from motor.motor_asyncio import AsyncIOMotorClient
import json
import os

router = APIRouter(prefix="/customers", tags=["Customers"])
NODEJS_API_BASE = "https://verce-ankurs-projects-b664b274.vercel.app/api/v1"  # Your Node.js API base URL
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# MongoDB Connection
MONGO_URI = os.getenv("MONGO_URI", "mongodb+srv://projectvaypar:Ankur@cluster0.vppsc.mongodb.net/")
db_client = AsyncIOMotorClient(MONGO_URI)
db = db_client.get_database("test")

# Pydantic Schemas
class CustomerCreate(BaseModel):
    name: str
    email: EmailStr
    phone: str

class CustomerUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    gstNumber: Optional[str] = None
    outstandingBill: Optional[float] = None
    TotalBill: Optional[float] = None

class CustomerDelete(BaseModel):
    name: str

# Utility functions to fetch customer IDs from MongoDB
async def get_customer_id(email: str):
    customer = await db.customers.find_one({"email": email})
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return str(customer["_id"])

async def get_customer_id_by_name(name: str):
    customer = await db.customers.find_one({"name": name})
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return str(customer["_id"])

def detect_intent(intent: str, data: Dict[str, Any]):
    if intent == "create_customer":
        return f"{NODEJS_API_BASE}/customer/customer-register", "POST", data
    elif intent == "update_customer":
        return f"{NODEJS_API_BASE}/customer/customer-register", "PUT", data
    elif intent == "delete_customer":
        return f"{NODEJS_API_BASE}/customer/customer-delete", "DELETE", data
    elif intent == "get_outstanding_bill":
        return f"{NODEJS_API_BASE}/customer/customer-outstanding", "GET", data
    elif intent == "get_total_bill":
        return f"{NODEJS_API_BASE}/customer/customer-totalBill", "GET", data
    elif intent == "get_customer_by_name":
        return f"{NODEJS_API_BASE}/dealer/get-by-name", "POST", data
    elif intent == "get_customer_details":
        return f"{NODEJS_API_BASE}/dealer/get-by-name", "POST", data
    else:
        raise HTTPException(status_code=400, detail=f"Invalid customer intent: {intent}")

async def handle_intent(intent: str, data: Dict[str, Any], token: str):
    # Override intent if it's get_outstanding_bill but only a name is provided.
    if intent == "get_outstanding_bill" and "name" in data and "customerId" not in data:
        intent = "get_customer_by_name"
    
    if intent in ["get_customer_by_name", "get_customer_details"]:
        if "name" not in data:
            raise HTTPException(status_code=400, detail="Name is required for getting customer details")
        data = {"name": data["name"]}
    elif intent in ["update_customer", "delete_customer", "get_outstanding_bill", "get_total_bill"]:
        if "customerId" not in data:
            if "email" in data:
                try:
                    data["customerId"] = await get_customer_id(data["email"])
                except Exception:
                    pass
            elif "name" in data:
                try:
                    data["customerId"] = await get_customer_id_by_name(data["name"])
                except Exception:
                    pass
    if intent == "update_customer":
        data = {k: v for k, v in data.items() if v is not None}

    url, method, payload = detect_intent(intent, data)
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
                if payload:
                    response = await client.request("GET", url, json=payload, headers=headers)
                else:
                    response = await client.get(url, headers=headers)
            else:
                raise HTTPException(status_code=500, detail="Unsupported HTTP method")
    
            if response.status_code >= 400:
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

@router.delete("/delete/by-name")
async def delete_customer_by_name(customer: CustomerDelete, token: str = Depends(oauth2_scheme)):
    data = customer.dict()
    result = await handle_intent("delete_customer", data, token)
    
    if result.get("status") != "success":
        raise HTTPException(status_code=400, detail=result.get("message"))
    
    return {
        "statusCode": 200,
        "data": result.get("data", result),
        "message": "Customer deleted successfully",
        "success": True,
        "status": "success",
        "conversation_id": "67d232676e7a77a715d19330"
    }

@router.post("/get/by-name")
async def fetch_customer_by_name(payload: Dict[str, Any], token: str = Depends(oauth2_scheme)):
    if "name" not in payload:
        raise HTTPException(status_code=400, detail="Name is required to fetch customer details")
    
    payload.pop("intent", None)
    result = await handle_intent("get_customer_by_name", payload, token)
    
    if result.get("status") != "success":
        raise HTTPException(status_code=400, detail=result.get("message"))
    
    return {
        "statusCode": 200,
        "data": result.get("data", result),
        "message": "Customer details retrieved successfully",
        "success": True,
        "status": "success",
        "conversation_id": "67d232676e7a77a715d19330"
    }
