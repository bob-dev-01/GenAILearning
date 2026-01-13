import os
import streamlit as st
import asyncio
import nest_asyncio

# Apply nest_asyncio to allow nested event loops in Streamlit
nest_asyncio.apply()

from dotenv import load_dotenv
from trello import TrelloClient

from llama_index.core import VectorStoreIndex, SimpleDirectoryReader, StorageContext, load_index_from_storage, Settings
from llama_index.core.tools import FunctionTool
# Workflow-based ReActAgent (default in 0.14.x)
from llama_index.core.agent import ReActAgent
from llama_index.core.memory import ChatMemoryBuffer
from llama_index.core.llms import ChatMessage
from llama_index.llms.gemini import Gemini
from llama_index.embeddings.gemini import GeminiEmbedding

# Load env variables
load_dotenv()

# --- CONFIGURATION ---
st.set_page_config(page_title="Audi Support Agent", layout="wide")

# Step A: Setup Gemini
try:
    llm = Gemini(model_name="models/gemini-2.0-flash-exp")
except:
    llm = Gemini(model_name="models/gemini-1.5-flash")

embed_model = GeminiEmbedding(model_name="models/text-embedding-004")

Settings.llm = llm
Settings.embed_model = embed_model

# Step B: Data Ingestion (RAG) - Cached globally
@st.cache_resource
def get_index():
    """Load and return index."""
    storage_dir = "./storage"
    
    if os.path.exists(storage_dir):
        storage_context = StorageContext.from_defaults(persist_dir=storage_dir)
        index = load_index_from_storage(storage_context)
    else:
        # If ragdocs missing, create it
        if not os.path.exists("ragdocs"):
            os.makedirs("ragdocs")
            
        documents = SimpleDirectoryReader("ragdocs").load_data()
        index = VectorStoreIndex.from_documents(documents)
        index.storage_context.persist(persist_dir=storage_dir)
    
    return index

# Init index and engine
index = get_index()
rag_engine = index.as_query_engine(similarity_top_k=3)

# Step C: Trello Integration
def create_ticket(user_name: str, user_email: str, summary: str, description: str) -> str:
    """Create a support ticket in Trello."""
    try:
        client = TrelloClient(
            api_key=os.environ["TRELLO_API_KEY"],
            token=os.environ["TRELLO_TOKEN"]
        )
        board = client.get_board(os.environ["TRELLO_BOARD_ID"])
        first_list = board.list_lists()[0]
        card = first_list.add_card(
            name=summary,
            desc=f"Name: {user_name}\nEmail: {user_email}\n\n{description}"
        )
        return f"Ticket created successfully! Link: {card.url}"
    except Exception as e:
        return f"Error creating ticket: {str(e)}"

# Step D: Agent Tools
def search_knowledge_base(query: str) -> str:
    """Search the Audi manuals for technical information."""
    response = rag_engine.query(query)
    
    sources = []
    for node in response.source_nodes:
        file_name = node.metadata.get("file_name", "Unknown File")
        page_label = node.metadata.get("page_label", "?")
        sources.append(f"{file_name} (Page {page_label})")
    
    unique_sources = list(set(sources))
    sources_str = "\n- ".join(unique_sources) if unique_sources else "No specific page found."
    return f"Answer based on manuals: {str(response)}\n\nSources:\n- {sources_str}"

ticket_tool = FunctionTool.from_defaults(fn=create_ticket)
rag_tool = FunctionTool.from_defaults(fn=search_knowledge_base)

SYSTEM_PROMPT = """
You are an expert Audi Customer Support Agent.
Your knowledge base consists of manuals for various Audi A-series models.

Process:
1. ALWAYS use 'search_knowledge_base' first to answer questions.
2. If the user does not specify the car model, ask them to clarify.
3. If the answer is NOT in the manuals, suggest creating a support ticket.
4. To create a ticket, ask for: Name, Email, Summary, Description.
"""

# --- UI LOGIC ---

st.title("🚗 Audi Support Agent")

if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if prompt := st.chat_input("Ask about your Audi (e.g., 'How to check oil in A4?')"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Analyzing manuals..."):
            
            # Helper to run async agent
            async def run_agent_interaction(user_prompt, history):
                # Build chat history for memory
                chat_history = [
                    ChatMessage(role=m["role"], content=m["content"])
                    for m in history
                ]
                memory = ChatMemoryBuffer.from_defaults(chat_history=chat_history)

                # Initialize Workflow Agent (ReActAgent in 0.14.x)
                # Note: 'system_prompt' might need to be passed via Context depending on version, 
                # but constructor usually accepts it or 'description'. 
                # ReActAgent(tools, llm, memory, ...)
                agent = ReActAgent(
                    tools=[ticket_tool, rag_tool],
                    llm=llm,
                    memory=memory,
                    timeout=120,
                    system_prompt=SYSTEM_PROMPT
                )
                
                return await agent.run(user_msg=user_prompt)

            # Execution with loop handling
            try:
                try:
                    loop = asyncio.get_event_loop()
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                
                response = loop.run_until_complete(run_agent_interaction(prompt, st.session_state.messages[:-1]))
                
                st.markdown(response.response)
                st.session_state.messages.append({"role": "assistant", "content": str(response.response)})

            except Exception as e:
                st.error(f"Error: {str(e)}")