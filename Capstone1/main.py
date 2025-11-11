import os
import json
import logging
import sqlite3
from dotenv import load_dotenv
import requests
import streamlit as st
import google.generativeai as genai

# =========================
#   Logging configuration
# =========================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

# =========================
#   Environment & Gemini init
# =========================
load_dotenv()

GOOGLE_API_KEY = os.getenv("google_api_key") or os.getenv("GOOGLE_API_KEY")
TRELLO_API_KEY = os.getenv("TRELLO_API_KEY")
TRELLO_TOKEN = os.getenv("TRELLO_TOKEN")
TRELLO_LIST_ID = os.getenv("TRELLO_LIST_ID")

if not GOOGLE_API_KEY:
    raise RuntimeError(
        "Google API key is missing. Set 'google_api_key' or 'GOOGLE_API_KEY' in .env"
    )

genai.configure(api_key=GOOGLE_API_KEY)

# =========================
#   DB schema description
# =========================
DB_SCHEMA_TEXT = """
You have two local SQLite databases.

1) airports.sqlite
   Table: airports_code
   Columns:
     - Airport_Code
     - Airport_Name
     - City_Name
     - Country_Name
     - Country_Code
     - Latitude
     - Longitude
     - World_Area_Code
     - City_Name_geo_name_id
     - Country_Name_geo_name_id
     - coordinates

2) movies.sqlite
   Table: directors
   Columns:
     - name
     - id
     - gender
     - uid
     - department

   Table: movies
   Columns:
     - id
     - original_title
     - budget
     - popularity
     - release_date
     - revenue
     - title
     - vote_average
     - vote_count
     - overview
     - tagline
     - uid
     - director_id

Rules:
- Use ONLY these tables and columns.
- Write queries in SQLite syntax.
- Only SELECT queries are allowed (no INSERT/UPDATE/DELETE/DDL).
- For airports, use the airports_code table.
- For movies, use the movies and directors tables (JOIN on movies.director_id = directors.id when needed).
""".strip()


# =========================
#   DB helper functions
# =========================
def get_row_count_airports() -> int:
    try:
        conn = sqlite3.connect("db/airports.sqlite")
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM airports_code")
        count = cur.fetchone()[0]
        conn.close()
        return count or 0
    except Exception as e:
        logging.error("Error counting airports rows: %s", e)
        return 0


def get_row_count_movies() -> int:
    try:
        conn = sqlite3.connect("db/movies.sqlite")
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM movies")
        count = cur.fetchone()[0]
        conn.close()
        return count or 0
    except Exception as e:
        logging.error("Error counting movies rows: %s", e)
        return 0


def get_sample_airports(limit: int = 5):
    try:
        conn = sqlite3.connect("db/airports.sqlite")
        cur = conn.cursor()
        cur.execute(
            "SELECT Airport_Code, Airport_Name, City_Name, Country_Name FROM airports_code LIMIT ?",
            (limit,),
        )
        rows = cur.fetchall()
        conn.close()
        return rows
    except Exception as e:
        logging.error("Error fetching sample airports: %s", e)
        return []


def get_sample_movies(limit: int = 5):
    try:
        conn = sqlite3.connect("db/movies.sqlite")
        cur = conn.cursor()
        cur.execute(
            "SELECT title, release_date, vote_average, vote_count FROM movies LIMIT ?",
            (limit,),
        )
        rows = cur.fetchall()
        conn.close()
        return rows
    except Exception as e:
        logging.error("Error fetching sample movies: %s", e)
        return []


# =========================
#   Tools (functions)
# =========================
def query_airports_db(query: str) -> str:
    """
    Execute a SQL query against db/airports.sqlite.

    SAFETY:
    - Only SELECT queries are allowed. Any other query type will be rejected.
    - This function should never modify schema or data.
    """
    logging.info("Tool query_airports_db called with query: %s", query)

    try:
        if not query.strip().lower().startswith("select"):
            logging.warning("Rejected non-SELECT query in query_airports_db: %s", query)
            return "Error: Only SELECT queries are allowed."

        conn = sqlite3.connect("db/airports.sqlite")
        cursor = conn.cursor()
        cursor.execute(query)
        rows = cursor.fetchall()
        col_names = [desc[0] for desc in cursor.description] if cursor.description else []
        conn.close()

        if not rows:
            logging.info("query_airports_db returned no results.")
            return "No results found."

        result = [dict(zip(col_names, row)) for row in rows]
        logging.info("query_airports_db returned %d rows.", len(result))
        return json.dumps(result, ensure_ascii=False)

    except Exception as e:
        logging.error("Error while querying airports.db: %s", e)
        return f"Error while querying airports.db: {e}"


def query_movies_db(query: str) -> str:
    """
    Execute a SQL query against db/movies.sqlite.

    SAFETY:
    - Only SELECT queries are allowed. Any other query type will be rejected.
    - This function should never modify schema or data.
    """
    logging.info("Tool query_movies_db called with query: %s", query)

    try:
        if not query.strip().lower().startswith("select"):
            logging.warning("Rejected non-SELECT query in query_movies_db: %s", query)
            return "Error: Only SELECT queries are allowed."

        conn = sqlite3.connect("db/movies.sqlite")
        cursor = conn.cursor()
        cursor.execute(query)
        rows = cursor.fetchall()
        col_names = [desc[0] for desc in cursor.description] if cursor.description else []
        conn.close()

        if not rows:
            logging.info("query_movies_db returned no results.")
            return "No results found."

        result = [dict(zip(col_names, row)) for row in rows]
        logging.info("query_movies_db returned %d rows.", len(result))
        return json.dumps(result, ensure_ascii=False)

    except Exception as e:
        logging.error("Error while querying movies.db: %s", e)
        return f"Error while querying movies.db: {e}"


def create_support_ticket(summary: str, details: str | None = None) -> str:
    """
    Create a support ticket in Trello.

    It will create a new card in a predefined Trello list.
    Trello credentials and list ID must be provided via environment variables:
    - TRELLO_API_KEY
    - TRELLO_TOKEN
    - TRELLO_LIST_ID
    """
    logging.info("Tool create_support_ticket called with summary: %s", summary)

    if not (TRELLO_API_KEY and TRELLO_TOKEN and TRELLO_LIST_ID):
        logging.error("Trello configuration is missing in environment variables.")
        return (
            "Support ticket could not be created: Trello configuration is missing "
            "(TRELLO_API_KEY, TRELLO_TOKEN, TRELLO_LIST_ID)."
        )

    url = "https://api.trello.com/1/cards"
    desc_parts = []
    if details:
        desc_parts.append(details)
    desc = "\n\n".join(desc_parts) if desc_parts else ""

    params = {
        "key": TRELLO_API_KEY,
        "token": TRELLO_TOKEN,
        "idList": TRELLO_LIST_ID,
        "name": summary,
        "desc": desc,
    }

    try:
        response = requests.post(url, params=params, timeout=10)
        logging.info("Trello API status code: %s", response.status_code)

        if response.status_code != 200:
            logging.error("Trello API error: %s", response.text)
            return f"Support ticket could not be created. Trello API error: {response.text}"

        data = response.json()
        card_id = data.get("id", "")
        card_url = data.get("shortUrl") or data.get("url", "")
        logging.info("Support ticket created: id=%s url=%s", card_id, card_url)

        return f"Support ticket created successfully. Card ID: {card_id}, URL: {card_url}"

    except Exception as e:
        logging.error("Error while creating Trello support ticket: %s", e)
        return f"Support ticket could not be created due to an internal error: {e}"


# =========================
#   Streamlit UI
# =========================
st.set_page_config(page_title="Data Insights App", page_icon="📊")
st.title("📊 Data Insights App — Gemini + SQLite + Trello")
st.caption("Ask questions about airports or movies data. The assistant uses tools to query the database and can create support tickets in Trello when needed.")

# Business info section (aggregated info + samples)
airports_count = get_row_count_airports()
movies_count = get_row_count_movies()

col1, col2 = st.columns(2)
with col1:
    st.metric("Airports (rows)", airports_count)
with col2:
    st.metric("Movies (rows)", movies_count)

st.markdown("### Sample queries")
st.markdown(
    "- *Show 5 airports in the United States.*\n"
    "- *How many movies were released after 2015 with rating above 7?*\n"
    "- *List top 10 most popular movies by vote count.*\n"
    "- *What is the average rating of movies directed by a specific director?*\n"
    "- *I need help with the data, please create a support ticket.*\n"
)

# Optional: show small sample tables
with st.expander("📌 Sample airports", expanded=False):
    rows = get_sample_airports(5)
    if rows:
        st.table(rows)
    else:
        st.info("No sample data available for airports.")

with st.expander("📌 Sample movies", expanded=False):
    rows = get_sample_movies(5)
    if rows:
        st.table(rows)
    else:
        st.info("No sample data available for movies.")


# Chat state
if "history" not in st.session_state:
    st.session_state.history = []

if "chat" not in st.session_state:
    # Configure Gemini model with tools and safety instructions
    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash",
        tools=[query_airports_db, query_movies_db, create_support_ticket],
        system_instruction=(
            "You are a data insights assistant working with two local SQLite databases: "
            "airports and movies. Use the provided tools to answer questions.\n\n"
            + DB_SCHEMA_TEXT
            + "\n\n"
            "Safety rules:\n"
            "- You must never write SQL that modifies data or schema. Only SELECT queries are allowed.\n"
            "- If the user explicitly asks to contact support or if you cannot answer the question with "
            "the available tools, suggest creating a support ticket and call the `create_support_ticket` tool "
            "with a concise summary and details of the issue.\n"
        ),
    )

    chat = model.start_chat(
        enable_automatic_function_calling=True
    )
    st.session_state.chat = chat

# Render existing chat history
for msg in st.session_state.history:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# Single user input -> single answer
user_input = st.chat_input("Ask a question about airports or movies data...")

if user_input:
    logging.info("User message: %s", user_input)

    st.session_state.history.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    chat = st.session_state.chat

    try:
        response = chat.send_message(user_input)
        # Log raw response object briefly
        try:
            logging.debug("Raw Gemini response: %s", response.to_dict())
        except Exception:
            logging.debug("Raw Gemini response (repr): %r", response)

        bot_reply = response.text or "(Empty response)"
        logging.info("Assistant reply: %s", bot_reply)

    except Exception as e:
        bot_reply = f"❌ Error from assistant: {e}"
        logging.error("Error during Gemini chat: %s", e)

    st.session_state.history.append({"role": "assistant", "content": bot_reply})
    with st.chat_message("assistant"):
        st.markdown(bot_reply)
