import os
from fastapi import FastAPI, HTTPException, Depends, Request, Header
from typing import Dict, Any, List, Optional
from customer import router as customer_router, detect_intent as customer_detect_intent, handle_intent as customer_handle_intent
from business import router as business_router, detect_intent as business_detect_intent, handle_intent as business_handle_intent
from product import router as product_router
from sales import router as sales_router
from dealer import handle_intent as dealer_handle_intent  # <-- NEW: Import dealer intent handler
from langchain_groq import ChatGroq
from langchain_community.tools.tavily_search import TavilySearchResults
from langgraph.prebuilt import create_react_agent
from langchain_core.messages.ai import AIMessage
from langchain_core.messages.human import HumanMessage
from pydantic import BaseModel
import json
import re
from fastapi.security import OAuth2PasswordBearer
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime
from bson import ObjectId
from dotenv import load_dotenv


from fastapi.middleware.cors import CORSMiddleware



# Load environment variables from .env file
load_dotenv()

app = FastAPI(title="Vypar app")


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Load API Keys
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

# MongoDB Connection
MONGO_URI = os.getenv("MONGO_URI", "mongodb+srv://projectvaypar:Ankur@cluster0.vppsc.mongodb.net/")
db_client = AsyncIOMotorClient(MONGO_URI)
db = db_client.get_database("test")

# OAuth2 scheme for token authentication
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# Include the specific routers
app.include_router(customer_router)
app.include_router(business_router)
app.include_router(product_router)
app.include_router(sales_router)

class IntentRequest(BaseModel):
    user_query: str
    conversation_id: Optional[str] = None
    # Allow additional fields for completing missing information
    additional_data: Optional[Dict[str, Any]] = None
    
class DetectedIntent(BaseModel):
    category: str
    intent: str
    data: Dict[str, Any]

# Get user's conversation history to maintain context
async def get_conversation_history(conversation_id: str, max_messages: int = 5):
    """
    Retrieve the recent conversation history for context
    """
    conversation = []
    if conversation_id:
        cursor = db.conversations.find({"conversation_id": conversation_id}).sort("timestamp", -1).limit(max_messages)
        async for message in cursor:
            conversation.append({
                "role": message["role"],
                "content": message["content"]
            })
        # Reverse to get chronological order
        conversation.reverse()
    return conversation

# Save conversation message to MongoDB
async def save_conversation_message(conversation_id: str, role: str, content: str, user_id: Optional[str] = None):
    """
    Save a conversation message to MongoDB
    """
    await db.conversations.insert_one({
        "conversation_id": conversation_id,
        "user_id": user_id,
        "role": role,
        "content": content,
        "timestamp": datetime.utcnow()
    })

def get_intent_from_ai_agent(query: str, conversation_history: List[Dict[str, Any]] = None):
    llm = ChatGroq(model="llama-3.3-70b-versatile")
    
    system_prompt = """
    You are an AI assistant that detects intents from user queries and extracts relevant data.
    Your task is to categorize the user's request into one of five categories: 'customer', 'business', 'product', 'sales', or 'dealer'.
    
    For each category, determine the specific intent:
    
    For 'customer' category:
    - create_customer: Create a new customer (requires name, email, phone)
    - update_customer: Update customer details (requires customerId and at least one field to update)
    - delete_customer: Delete a customer (requires customerId)
    - get_outstanding_bill: Get customer's outstanding bill (requires customerId)
    - get_total_bill: Get customer's total bill (requires customerId)
    
    For 'business' category:
    - register_business: Register a new business (requires name, phone, address, pincode, state, businessCategory, businessType)
    - update_business: Update business details (requires businessId or name and at least one field to update)
    - delete_business: Delete a business (requires businessId or name)
    - get_business_details: Get business details (requires businessId or name)
    
    For 'product' category:
    - create_product: Create a new product (requires name, gstRate, rate)
    - update_product: Update product details (requires productId and at least one field to update)
    - delete_product: Delete a product (requires productId)
    - get_product_by_name: Get product by name (requires name)
    - get_all_products: Get all products of the dealer (no additional fields required; dealer id is taken from the token)

    
    For 'sales' category:
    - create_sale: Create a new sale (requires customerId, products array, paymentMethod, optional amountPaid)
    - generate_invoice: Generate an invoice (requires saleId, recipientEmail)
    
    For 'dealer' category:
    - get_outstanding_bill: Get dealer's outstanding bill (no additional fields required; dealer id is taken from the token)
    - get_total_bill: Get dealer's total bill (no additional fields required; dealer id is taken from the token)
    - get_pending_balance: Get all customers with pending balance (no additional fields required; dealer id is taken from the token)
    - get_all_customer: Get all customers (no additional fields required; dealer id is taken from the token)
    - get_weekly_sale: Get dealer's weekly sale (no additional fields required; dealer id is taken from the token)
    - get_monthly_sale: Get dealer's monthly sale (no additional fields required; dealer id is taken from the token)
    - get_value_sale: Get top customers by business value (no additional fields required; dealer id is taken from the token)
    
    Extract all relevant data for the detected intent.
    Respond with a JSON object containing 'category', 'intent', and 'data' fields.
    """
    # ... rest of the function remains unchanged


    
    agent = create_react_agent(model=llm, tools=[], state_modifier=system_prompt)
    
    messages = []
    
    # Add conversation history for context if available
    if conversation_history:
        for msg in conversation_history:
            if msg["role"] == "user":
                messages.append(HumanMessage(content=msg["content"]))
            elif msg["role"] == "assistant":
                messages.append(AIMessage(content=msg["content"]))
    
    # Add the current query
    messages.append(HumanMessage(content=query))
    state = {"messages": messages}
    
    response = agent.invoke(state)
    ai_messages = [message for message in response.get("messages", []) if isinstance(message, AIMessage)]
    
    if not ai_messages:
        raise HTTPException(status_code=500, detail="Failed to process intent with AI")
    
    try:
        response_content = ai_messages[-1].content
        json_match = re.search(r'```json\s*(.*?)\s*```', response_content, re.DOTALL)
        json_str = json_match.group(1) if json_match else response_content
        json_str = re.sub(r'^[^{]*({.*})[^}]*$', r'\1', json_str, flags=re.DOTALL)
        intent_data = json.loads(json_str)
        return intent_data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse intent from AI response: {str(e)}")

# Check if all required fields are present for an intent
def check_required_fields(category: str, intent: str, data: Dict[str, Any]):
    required_fields = []
    
    if category == "customer":
        if intent == "create_customer":
            required_fields = ["name", "email", "phone"]
        elif intent in ["update_customer", "delete_customer", "get_outstanding_bill", "get_total_bill"]:
            if "customerId" not in data and "name" not in data and "email" not in data:
                required_fields = ["customerId"] 
        elif intent in ["get_customer_by_name", "get_customer_details"]:
            required_fields = ["name"]
                
    elif category == "business":
        if intent == "register_business":
            required_fields = ["name", "phone", "address", "pincode", "state", "businessCategory", "businessType"]
        elif intent == "update_business":
            # Do not require any fields from the AI agent—
            # the update handler will fetch the business record (and its name) using the token.
            required_fields = []
                
    elif category == "product":
        if intent == "create_product":
            required_fields = ["name", "gstRate", "rate"]
        elif intent in ["update_product", "delete_product"]:
            required_fields = ["productId"]
        elif intent == "get_product_by_name":
            required_fields = ["name"]
        elif intent == "get_all_products":
            required_fields = []  # No additional fields are needed since dealer id is from the token

    elif category == "sales":
        if intent == "create_sale":
            required_fields = ["customerId", "products", "paymentMethod"]
        elif intent == "generate_invoice":
            required_fields = ["saleId", "recipientEmail"]
    elif category == "dealer":
        if intent in [
            "get_outstanding_bill", "get_total_bill", "get_pending_balance", 
            "get_all_customer", "get_weekly_sale", "get_monthly_sale", "get_value_sale"
        ]:
            required_fields = []  # No additional data is needed; dealer id comes from the token

    missing_fields = [field for field in required_fields if field not in data or data[field] is None]
    return missing_fields


# Helper function to extract token from Authorization header
async def get_token_from_authorization(authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header missing")
    
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid authorization header format")
    
    return parts[1]

# Generate a new conversation ID
def generate_conversation_id():
    return str(ObjectId())

@app.post("/process-query")
async def process_natural_language_query(
    request: IntentRequest,
    token: str = Depends(get_token_from_authorization)
):
    """
    Process a natural language query to determine intent and action
    Also handles completing intents with missing fields via additional_data
    """
    # Get conversation ID or create a new one
    conversation_id = request.conversation_id
    if not conversation_id:
        conversation_id = generate_conversation_id()
    
    # Get conversation history for context
    conversation_history = await get_conversation_history(conversation_id)
    
    # Check if this is a follow-up with additional data for missing fields
    previous_intent = None
    if request.additional_data and len(conversation_history) > 0:
        # Try to find the last saved intent in the conversation history
        for message in reversed(conversation_history):
            if message["role"] == "assistant" and "missing_fields" in message["content"]:
                try:
                    # Look for stored intent in the last missing_fields response
                    stored_intent_match = re.search(r'"stored_intent":\s*({.*?})', message["content"])
                    if stored_intent_match:
                        previous_intent = json.loads(stored_intent_match.group(1))
                        break
                except:
                    pass
    
    # Save user query to conversation history
    await save_conversation_message(conversation_id, "user", request.user_query, user_id=None)
    
    # If we have a previous intent with missing fields and additional data, use that
    if previous_intent and request.additional_data:
        intent_data = previous_intent
        # Update the data with the additional fields provided
        for field, value in request.additional_data.items():
            if value is not None:
                intent_data["data"][field] = value
    else:
        # Get intent from AI agent
        intent_data = get_intent_from_ai_agent(request.user_query, conversation_history)
    
    if not all(k in intent_data for k in ["category", "intent", "data"]):
        raise HTTPException(status_code=500, detail="Invalid intent format from AI")
    
    category = intent_data["category"]
    intent = intent_data["intent"]
    data = intent_data["data"]
    
    # Check for missing required fields
    missing_fields = check_required_fields(category, intent, data)
    
    # If fields are missing, ask the user to provide them
    if missing_fields:
        # Store the current intent in the response for later continuation
        stored_intent_json = json.dumps(intent_data)
        
        response = {
            "status": "missing_fields",
            "message": f"Please provide the following information: {', '.join(missing_fields)}",
            "required_fields": missing_fields,
            "conversation_id": conversation_id,
            "stored_intent": intent_data,
            "how_to_proceed": "Please send another request to /process-query with the same conversation_id and the missing fields in the additional_data field."
        }
        
        # Save assistant response to conversation history including the stored intent
        response_content = f"Please provide the following information: {', '.join(missing_fields)}. \"stored_intent\": {stored_intent_json}"
        await save_conversation_message(conversation_id, "assistant", response_content)
        
        return response
    
    # Process the intent with the appropriate handler
    try:
        if category == "customer":
            result = await customer_handle_intent(intent, data, token)
        elif category == "business":
            result = await business_handle_intent(intent, data, token)
        elif category == "product":
            result = await product_router.handle_intent(intent, data, token)
        elif category == "sales":
            result = await sales_router.handle_intent(intent, data, token)
        elif category == "dealer":  # <-- NEW: Handle dealer intent
            result = await dealer_handle_intent(intent, data, token)
        else:
            raise HTTPException(status_code=400, detail=f"Invalid category: {category}")
        
        # Save the successful response to conversation history
        response_content = json.dumps(result) if isinstance(result, dict) else str(result)
        await save_conversation_message(conversation_id, "assistant", response_content)
        
        # Add conversation_id to the response
        if isinstance(result, dict):
            result["conversation_id"] = conversation_id
        else:
            result = {"result": result, "conversation_id": conversation_id}
        
        return result
    
    except Exception as e:
        error_message = str(e)
        # Save the error response to conversation history
        await save_conversation_message(conversation_id, "assistant", f"Error: {error_message}")
        raise HTTPException(status_code=500, detail=error_message)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
