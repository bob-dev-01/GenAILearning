# Audi Support Agent

A Streamlit-based RAG application that answers technical questions about Audi vehicles using Gemini and LlamaIndex.

## Features
- **RAG Powered**: Uses LlamaIndex and Gemini to answer questions from Audi manuals.
- **Trello Integration**: Can create support tickets directly in Trello.
- **Robust Design**: Uses stateless agent interaction for stability on Streamlit.

## Setup
1.  **Environment Variables**:
    Create a `.env` file with:
    ```
    GOOGLE_API_KEY=your_key
    TRELLO_API_KEY=your_key
    TRELLO_TOKEN=your_token
    TRELLO_BOARD_ID=your_board_id
    ```

2.  **Install**:
    ```bash
    pip install -r requirements.txt
    ```

3.  **Run**:
    ```bash
    streamlit run app.py
    ```

## Deployment (Hugging Face)
This project is ready for Hugging Face Spaces.
1.  Create a standardized `requirements.txt`.
2.  Set secrets in the Space settings (not in `.env`).
3.  Upload `ragdocs/` (PDF manuals).
