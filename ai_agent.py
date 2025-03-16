import os
from langchain_groq import ChatGroq
from langchain_community.tools.tavily_search import TavilySearchResults
from langgraph.prebuilt import create_react_agent
from langchain_core.messages.ai import AIMessage

# Load API Keys
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

def get_response_from_ai_agent(llm_id, query, allow_search, system_prompt):
    # Ensure it always uses Groq with LLaMA
    llm = ChatGroq(model=llm_id)  # Only using Groq (LLaMA models)

    tools = [TavilySearchResults(max_results=2)] if allow_search else []
    agent = create_react_agent(model=llm, tools=tools, state_modifier=system_prompt)
    
    state = {"messages": query}
    response = agent.invoke(state)
    messages = response.get("messages")
    
    ai_messages = [message.content for message in messages if isinstance(message, AIMessage)]
    return ai_messages[-1] if ai_messages else "No response generated."

# Example Usage
llm_id = "llama-3.3-70b-versatile"  # Always using LLaMA
query = "Explain the impact of AI on software development."
response = get_response_from_ai_agent(llm_id, query, allow_search=False, system_prompt="Provide a detailed answer.")

print(response)
