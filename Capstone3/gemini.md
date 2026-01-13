# Project Instructions: LlamaIndex + Gemini 2.0 Support Agent

**Role:** You are a Python expert specializing in LlamaIndex and Streamlit.
**Objective:** Build a minimal, functional Customer Support RAG Agent deployed on HuggingFace Spaces.
**Strict Constraint:** Code must be minimal. Follow the "Happy Path" only. No defensive programming or complex error handling.

## Tech Stack & Configuration
1.  **LLM:** Google Gemini 2.0 Flash (`models/gemini-2.0-flash-exp` or `models/gemini-1.5-flash` if 2.0 is not yet available in the library).
2.  **Framework:** LlamaIndex (latest).
3.  **UI:** Streamlit.
4.  **Integrations:** Trello API (`py-trello`).
5.  **Hosting:** HuggingFace Spaces.
6.  **Data Source:** PDF files located in local folder `ragdocs/`.

## Environment Variables (User must provide these in `.env` or Secrets)
*   `GOOGLE_API_KEY`
*   `TRELLO_API_KEY`
*   `TRELLO_TOKEN`
*   `TRELLO_BOARD_ID`

## Required Files & Implementation Details

### 1. `requirements.txt`
Generate strict dependencies:
*   `streamlit`
*   `llama-index`
*   `llama-index-llms-gemini`
*   `llama-index-embeddings-gemini`
*   `py-trello`
*   `python-dotenv`

### 2. `app.py` (The Single Entry Point)
Implement the entire logic here using `@st.cache_resource` to handle index loading/creation efficiently on HuggingFace.

**Step A: Setup Gemini**
*   Initialize `Gemini` with `model_name="models/gemini-2.0-flash-exp"`.
*   Initialize `GeminiEmbedding` with `model_name="models/text-embedding-004"`.
*   Set these as global `Settings` in LlamaIndex.

**Step B: Data Ingestion (RAG)**
*   Write a function `get_index()` decorated with `@st.cache_resource`.
*   Logic:
    *   Check if `./storage` directory exists.
    *   If **Yes**: Load index via `load_index_from_storage`.
    *   If **No**: Read PDFs from `ragdocs/`, create `VectorStoreIndex`, and persist to `./storage`.
*   *Note:* This ensures the app builds the index on the first run in HuggingFace.

**Step C: Trello Integration**
*   Create a simple function `create_ticket(user_name, user_email, summary, description)`.
*   Use `TrelloClient`. Get the board by ID. Add the card to the **first list** on that board.
*   Return a string: "Ticket [ID] created: [URL]".

**Step D: Agent Logic (Function Calling)**
*   Create two tools using `FunctionTool`:
    1.  `ticket_tool`: Wraps `create_ticket`.
    2.  `rag_tool`: Wraps a custom search function.
*   **Crucial - RAG Tool Implementation:**
    *   The search function must query the index engine.
    *   It MUST parse `response.source_nodes`.
    *   Extract `file_name` and `page_label` from metadata.
    *   Format the return string: `"{Answer from LLM} \n\nSources: {file_name} (Page {page_label}) ..."`.
*   Initialize `ReActAgent` (from `llama_index.core.agent`) with these 2 tools and the Gemini LLM.
*   **System Prompt:** 
    "You are an expert Audi Customer Support Agent. 
    Your knowledge base consists of manuals for various Audi A-series models.
    
    Rules:
    1. Always try to answer using the 'rag_tool' first.
    2. Since you have manuals for different models (e.g., A3, A4, A6), pay attention to which car the user is asking about. If not specified, ask for the model.
    3. If the answer is not found in the manuals, suggest creating a support ticket.
    4. To create a ticket, you MUST ask for Name, Email, Summary, and Description.
    5. Always rely on the tool output for answers and keep the tone professional and helpful."

**Step E: Streamlit UI**
*   Title: "Support Agent (Gemini Powered)".
*   Initialize `st.session_state.messages` and `st.session_state.agent`.
*   Render chat history.
*   On user input:
    *   Append user msg to state.
    *   Call `agent.chat(user_input)`.
    *   Append response to state.
    *   Display response.

## Execution
Generate the full code for `requirements.txt` and `app.py`.