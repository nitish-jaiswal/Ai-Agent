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


import jwt
from jwt import PyJWTError

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
async def get_conversation_history(conversation_id: str = None, user_id: str = None, max_messages: int = 5):
    """
    Retrieve the recent conversation history for context, filtered by user_id from the token
    """
    conversation = []
    query = {}
    
    # If we have a user_id from the token, use it to filter conversations
    if user_id:
        query["user_id"] = user_id
    
    # If we also have a conversation_id, add it to ensure we're getting the right conversation
    if conversation_id:
        query["conversation_id"] = conversation_id
    
    cursor = db.conversations.find(query).sort("timestamp", -1).limit(max_messages)
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
    - get_all_products: Get my all products (no additional fields required; dealer id is taken from the token)

    
    For 'sales' category:
    - create_sale: Create a new sale (requires customerId, products array, paymentMethod, optional amountPaid)
    - generate_invoice: Generate an invoice (requires saleId, recipientEmail)
    
    For 'dealer' category:
    - get_outstanding_bill: Get my outstanding bill (no additional fields required; dealer id is taken from the token)
    - get_total_bill: Get my total bill (no additional fields required; dealer id is taken from the token)
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
    print("=== TOKEN EXTRACTION DEBUG ===")
    print(f"Authorization header received: {authorization[:15]}..." if authorization else "No authorization header")
    
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header missing")
    
    parts = authorization.split()
    print(f"Split parts: {parts[0]} {parts[1][:10]}..." if len(parts) > 1 else f"Parts: {parts}")
    
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid authorization header format")
    
    token = parts[1]
    print(f"Extracted token: {token[:10]}...")
    return token

def get_user_id_from_token(token: str):
    print("=== TOKEN DECODING DEBUG ===")
    print(f"Token to decode: {token[:15]}...")
    
    try:
        # First, check if it's a valid JWT format
        parts = token.split('.')
        print(f"Token parts: {len(parts)}")
        
        if len(parts) != 3:
            print("WARNING: Token does not have 3 parts as expected for JWT")
        
        # Try decoding without verification
        print("Attempting to decode token...")
        payload = jwt.decode(token, options={"verify_signature": False})
        print(f"Decoded payload: {payload}")
        
        # Try different possible id fields
        user_id = payload.get("_id")
        print(f"Extracted _id: {user_id}")
        
        if not user_id:
            # Check for other possible ID fields
            user_id = payload.get("id") or payload.get("userId") or payload.get("user_id")
            print(f"Tried alternate ID fields, got: {user_id}")
            
            # If still not found, look for any *id field
            if not user_id:
                for key, value in payload.items():
                    if key.lower().endswith('id'):
                        user_id = value
                        print(f"Found ID in field '{key}': {value}")
                        break
        
        return user_id
    except Exception as e:
        print(f"Error decoding token: {str(e)}")
        print(f"Error type: {type(e).__name__}")
        return None

def generate_conversation_id(token: str):
   
    
    # Extract user ID from token
    user_id = get_user_id_from_token(token)
    print(f"User ID extracted from token: {user_id}")
    
    if not user_id:
        # Fallback to random ID if token can't be decoded
        result = str(ObjectId())
        print(f"No user ID found, using random ID: {result}")
        return result
    
    # Use the user ID directly as the conversation ID
    print(f"Using user ID as conversation ID: {user_id}")
    return user_id
# Generate a new conversation ID
async def find_previous_data(category: str, intent: str, user_id: str):
    """
    Search previous conversations for relevant data for the specified intent
    """
    previous_data = {}
    
    # Define fields to look for based on intent
    fields_to_find = []
    if category == "customer" and intent == "create_customer":
        fields_to_find = ["name", "email", "phone"]
    elif category == "business" and intent == "register_business":
        fields_to_find = ["name", "phone", "address", "pincode", "state", "businessCategory", "businessType"]
    # Add similar conditions for other intents
    
    # Search in conversation history
    if fields_to_find:
        cursor = db.conversations.find({"user_id": user_id}).sort("timestamp", -1)
        async for message in cursor:
            if message["role"] == "assistant" and "result" in message["content"]:
                try:
                    # Try to parse the content as JSON
                    content = json.loads(message["content"])
                    if isinstance(content, dict) and "data" in content:
                        for field in fields_to_find:
                            if field in content["data"] and field not in previous_data:
                                previous_data[field] = content["data"][field]
                except:
                    pass
    
    return previous_data if previous_data else None


@app.post("/process-query")
async def process_natural_language_query(
    request: IntentRequest,
    token: str = Depends(get_token_from_authorization)
):
    user_id = get_user_id_from_token(token)
    
    # Get conversation ID or create a new one
    conversation_id = request.conversation_id
    if not conversation_id:
        conversation_id = generate_conversation_id(token)
    
    # Get conversation history for context
    conversation_history = await get_conversation_history(conversation_id=None, user_id=user_id)
    
    # Save user query to conversation history
    await save_conversation_message(conversation_id, "user", request.user_query, user_id=user_id)
    
    # Check if this is a follow-up to a previous intent with missing fields
    previous_intent = None
    missing_fields = []
    
    # If the query contains "yes" or "use that data" or similar confirmations
    # and we have a stored intent with suggested data, use that data
    if re.search(r'\b(yes|yeah|correct|use (?:that|this|the) data|confirm)\b', request.user_query.lower()):
        for message in reversed(conversation_history):
            if message["role"] == "assistant" and "suggested_data" in message["content"]:
                try:
                    suggested_data_match = re.search(r'"suggested_data":\s*({.*?})', message["content"])
                    stored_intent_match = re.search(r'"stored_intent":\s*({.*?})', message["content"])
                    if suggested_data_match and stored_intent_match:
                        suggested_data = json.loads(suggested_data_match.group(1))
                        previous_intent = json.loads(stored_intent_match.group(1))
                        # Update the intent data with the suggested data
                        for field, value in suggested_data.items():
                            previous_intent["data"][field] = value
                        break
                except Exception as e:
                    print(f"Error parsing previous suggestion: {str(e)}")
                    continue
    
    # Look for the most recent intent with missing fields in the conversation history
    if not previous_intent:
        for message in reversed(conversation_history):
            if message["role"] == "assistant" and "missing_fields" in message["content"]:
                try:
                    # Extract the stored intent
                    stored_intent_match = re.search(r'"stored_intent":\s*({.*?})', message["content"])
                    if stored_intent_match:
                        previous_intent = json.loads(stored_intent_match.group(1))
                        # Extract missing fields from the message
                        missing_fields_match = re.search(r'Please provide the following information: (.*?)\.', message["content"])
                        if missing_fields_match:
                            missing_fields = [field.strip() for field in missing_fields_match.group(1).split(',')]
                        break
                except Exception as e:
                    print(f"Error parsing previous intent: {str(e)}")
                    continue
    
    # If we have a previous intent with missing fields, try to extract the missing information
    if previous_intent and missing_fields:
        # Extract any additional information from the current query
        new_intent_data = get_intent_from_ai_agent(request.user_query, conversation_history)
        
        # Update the previous intent with any new information
        for field, value in new_intent_data["data"].items():
            if value is not None:
                previous_intent["data"][field] = value
        
        # Add any explicitly provided additional data
        if request.additional_data:
            for field, value in request.additional_data.items():
                if value is not None:
                    previous_intent["data"][field] = value
                    
        # Try to extract information from previous user messages
        for message in reversed(conversation_history):
            if message["role"] == "user":
                try:
                    user_message_intent = get_intent_from_ai_agent(message["content"], [])
                    for field, value in user_message_intent["data"].items():
                        if field not in previous_intent["data"] or previous_intent["data"][field] is None:
                            previous_intent["data"][field] = value
                except Exception:
                    continue
        
        intent_data = previous_intent
    else:
        # No previous intent with missing fields, get a new intent
        intent_data = get_intent_from_ai_agent(request.user_query, conversation_history)
    
    if not all(k in intent_data for k in ["category", "intent", "data"]):
        raise HTTPException(status_code=500, detail="Invalid intent format from AI")
    
    category = intent_data["category"]
    intent = intent_data["intent"]
    data = intent_data["data"]
    
    # Check for missing required fields
    missing_fields = check_required_fields(category, intent, data)
    
    # Check for previous data if we have missing fields
    if missing_fields:
        previous_data = await find_previous_data(category, intent, user_id)
        
        if previous_data and any(field in previous_data for field in missing_fields):
            # Filter to only include the fields we need
            suggested_data = {field: previous_data[field] for field in missing_fields if field in previous_data}
            
            # If we found data for at least some of the missing fields
            if suggested_data:
                # Store the current intent and suggested data in the response
                stored_intent_json = json.dumps(intent_data)
                suggested_data_json = json.dumps(suggested_data)
                
                # Update the missing fields to exclude fields we have suggestions for
                missing_fields = [field for field in missing_fields if field not in suggested_data]
                
                # Prepare the message to show to the user
                fields_with_values = [f"{field}: {value}" for field, value in suggested_data.items()]
                fields_display = ", ".join(fields_with_values)
                
                if missing_fields:
                    response = {
                        "status": "suggested_data_with_missing_fields",
                        "message": f"I found the following information from your previous conversations: {fields_display}. Would you like to use this data? Also, please provide the following missing information: {', '.join(missing_fields)}",
                        "suggested_data": suggested_data,
                        "remaining_fields": missing_fields,
                        "conversation_id": conversation_id,
                        "stored_intent": intent_data
                    }
                else:
                    response = {
                        "status": "suggested_data",
                        "message": f"I found the following information from your previous conversations: {fields_display}. Would you like to use this data?",
                        "suggested_data": suggested_data,
                        "conversation_id": conversation_id,
                        "stored_intent": intent_data
                    }
                
                # Save assistant response to conversation history including the stored intent and suggested data
                response_content = f"{response['message']} \"stored_intent\": {stored_intent_json}, \"suggested_data\": {suggested_data_json}"
                await save_conversation_message(conversation_id, "assistant", response_content, user_id=user_id)
                
                return response
    
    # If fields are still missing (and we don't have suggested data for them)
    if missing_fields:
        # Store the current intent in the response for later continuation
        stored_intent_json = json.dumps(intent_data)
        
        response = {
            "status": "missing_fields",
            "message": f"Please provide the following information: {', '.join(missing_fields)}",
            "required_fields": missing_fields,
            "conversation_id": conversation_id,
            "stored_intent": intent_data,
            "how_to_proceed": "Please continue the conversation with the missing information."
        }
        
        # Save assistant response to conversation history including the stored intent
        response_content = f"Please provide the following information: {', '.join(missing_fields)}. \"stored_intent\": {stored_intent_json}"
        await save_conversation_message(conversation_id, "assistant", response_content, user_id=user_id)
        
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
        elif category == "dealer":
            result = await dealer_handle_intent(intent, data, token)
        else:
            raise HTTPException(status_code=400, detail=f"Invalid category: {category}")
        
        # Save the successful response to conversation history
        response_content = json.dumps(result) if isinstance(result, dict) else str(result)
        await save_conversation_message(conversation_id, "assistant", response_content, user_id=user_id)
        
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
