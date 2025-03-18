import httpx
import logging
from fastapi import HTTPException

logging.basicConfig(level=logging.INFO)

async def handle_intent(intent: str, data: dict, token: str):
    """
    Handle dealer intents.
    
    The backend API extracts the dealer id from the token via middleware.
    """
    headers = {"Authorization": f"Bearer {token}"}
    
    # All endpoints share the same base URL.
    base_url = "https://verce-ankurs-projects-b664b274.vercel.app/api/v1/dealer"
    
    if intent == "get_outstanding_bill":
        url = f"{base_url}/outstanding-bill"
    elif intent == "get_total_bill":
        url = f"{base_url}/total-bill"
    elif intent == "get_pending_balance":
        url = f"{base_url}/pending-balance"
    elif intent == "get_all_customer":
        url = f"{base_url}/get-all-customer"
    elif intent == "get_weekly_sale":
        url = f"{base_url}/weekly-sale"
    elif intent == "get_monthly_sale":
        url = f"{base_url}/monthly-sale"
    elif intent == "get_value_sale":
        url = f"{base_url}/value-sale"
    else:
        raise HTTPException(status_code=400, detail=f"Invalid dealer intent: {intent}")

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, headers=headers)
        
        logging.info(f"Called URL: {url}")
        logging.info(f"Request Headers: {headers}")
        logging.info(f"Response status code: {response.status_code}")
        logging.info(f"Response body: {response.text}")
        
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail=response.text)
        
        return response.json()
    
    except Exception as e:
        logging.error(f"Error while calling dealer API: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error while calling dealer API: {str(e)}")
