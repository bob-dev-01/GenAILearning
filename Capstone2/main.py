import base64
import hashlib
import logging
import os
import tempfile
import time
from io import BytesIO

import streamlit as st
from dotenv import load_dotenv
from google import genai
from streamlit_mic_recorder import mic_recorder
import assemblyai as aai
import PIL.Image as PILImage
from bytez import Bytez  # Bytez SDK

# ======================================
# Logging configuration
# ======================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

# ======================================
# Environment & API clients
# ======================================
load_dotenv()

# Gemini (image generation)
GOOGLE_API_KEY = os.getenv("google_api_key") or os.getenv("GOOGLE_API_KEY")
if not GOOGLE_API_KEY:
    raise RuntimeError(
        "Google API key is missing. "
        "Set 'google_api_key' or 'GOOGLE_API_KEY' in your environment or .env file."
    )
gemini_client = genai.Client(api_key=GOOGLE_API_KEY)
IMAGE_MODEL = "gemini-2.5-flash-image"

# AssemblyAI (STT)
ASSEMBLYAI_API_KEY = os.getenv("ASSEMBLYAI_API_KEY") or os.getenv("assemblyai_api_key")
if not ASSEMBLYAI_API_KEY:
    raise RuntimeError(
        "AssemblyAI API key is missing. "
        "Set 'ASSEMBLYAI_API_KEY' in your environment or .env file."
    )
aai.settings.api_key = ASSEMBLYAI_API_KEY

# Bytez (LLM → image prompt)
BYTEZ_API_KEY = os.getenv("BYTEZ_API_KEY") or os.getenv("bytez_api_key")
if not BYTEZ_API_KEY:
    raise RuntimeError(
        "BYTEZ_API_KEY is missing. "
        "Set 'BYTEZ_API_KEY' in your environment or .env file."
    )
bytez = Bytez(BYTEZ_API_KEY)
BYTEZ_MODEL_ID = "openai/gpt-4o-mini"  # can be changed to "openai/gpt-4o" if needed


# ======================================
# Helper: STT via AssemblyAI
# ======================================
def transcribe_with_assemblyai(file_bytes: bytes) -> str:
    """
    Transcribe audio using AssemblyAI (synchronous).
    """
    logging.info("Sending audio to AssemblyAI, size=%s bytes", len(file_bytes))

    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name

    logging.info("Temporary audio file for AssemblyAI: %s", tmp_path)

    try:
        transcriber = aai.Transcriber()
        transcript = transcriber.transcribe(tmp_path)

        logging.info("AssemblyAI transcription status: %s", transcript.status)
        if transcript.status != "completed":
            raise RuntimeError(
                f"Transcription failed: {transcript.status} ({transcript.error})"
            )

        text = (transcript.text or "").strip()
        logging.info("AssemblyAI transcript text: %s", text)
        return text

    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass


# ======================================
# Helper: text → image prompt via Bytez
# ======================================
def build_image_prompt_with_bytez(user_text: str) -> str:
    """
    Use Bytez (openai/gpt-4o-mini) to convert transcription text into
    an image-generation prompt.

    Bytez Python SDK returns a Response object: Response(output=..., error=..., provider=...).
    Inside output there is usually a dict like:
        {"role": "assistant", "content": "...prompt text..."}
    We need the 'content' string.
    """
    if not BYTEZ_API_KEY:
        raise RuntimeError("BYTEZ_API_KEY is not set. Cannot call Bytez API.")

    logging.info("Building image prompt with Bytez model=%s", BYTEZ_MODEL_ID)

    system_instruction = (
        "You convert short user requests into detailed prompts for image generation models. "
        "Be specific about scene, subjects, composition, camera/perspective, lighting, colors, art style, and mood. "
        "Output only the final English prompt, no explanations."
    )

    model = bytez.model(BYTEZ_MODEL_ID)

    messages = [
        {"role": "system", "content": system_instruction},
        {"role": "user", "content": f"User request: {user_text}"},
    ]

    result = model.run(messages)
    logging.info("Raw Bytez result (type=%s): %r", type(result), result)

    output = None
    error = None

    # Bytez.Response: has attributes output / error
    if hasattr(result, "output") or hasattr(result, "error"):
        error = getattr(result, "error", None)
        output = getattr(result, "output", None)
    # Tuple/list fallback
    elif isinstance(result, (tuple, list)):
        if len(result) >= 1:
            output = result[0]
        if len(result) >= 2:
            error = result[1]
    # Dict fallback
    elif isinstance(result, dict):
        output = result.get("output")
        error = result.get("error")
    else:
        output = result

    if error:
        logging.error("Bytez error: %r", error)
        raise RuntimeError(f"Bytez API error: {error}")

    if output is None:
        raise RuntimeError(f"Bytez returned empty output: {result!r}")

    # If output is dict like {"role": "...", "content": "..."}
    if isinstance(output, dict):
        content = output.get("content")
        if content is None:
            raise RuntimeError(f"Bytez output has no 'content': {output!r}")
        output = content

    if not isinstance(output, str):
        output = str(output)

    prompt = output.strip()
    logging.info("Bytez image prompt (string): %s", prompt)
    return prompt


# ======================================
# Helper: prompt → image via Gemini
# ======================================
def generate_image_with_gemini(prompt: str) -> PILImage.Image:
    """
    Generate an image from a text prompt using gemini-2.5-flash-image (Nano Banana).
    Returns a real PIL.Image.Image and robustly handles inline_data.data,
    which may be a base64 string or raw bytes.
    """
    logging.info("Generating image with Gemini model=%s", IMAGE_MODEL)
    logging.info("Prompt for image generation: %s", prompt)

    try:
        # As in the official docs — just pass the string prompt
        resp = gemini_client.models.generate_content(
            model=IMAGE_MODEL,
            contents=[prompt],
        )

        # In the newer client, image models return resp.parts
        parts = []
        if getattr(resp, "parts", None):
            parts = resp.parts
        elif getattr(resp, "candidates", None):
            # Fallback to candidates if a different structure appears
            parts = resp.candidates[0].content.parts
        else:
            raise RuntimeError(f"Unexpected Gemini image response structure: {resp}")

        if not parts:
            raise RuntimeError(f"No parts in Gemini image response: {resp}")

        for part in parts:
            inline = getattr(part, "inline_data", None)
            if inline is None:
                continue

            data = getattr(inline, "data", None)
            if data is None:
                continue

            logging.info(
                "Got inline_data from Gemini: type=%s, len=%s",
                type(data),
                len(data) if hasattr(data, "__len__") else "n/a",
            )

            # 1) If it's already raw bytes — use as-is
            if isinstance(data, (bytes, bytearray)):
                image_bytes = bytes(data)
            # 2) If it's a string — try to decode as base64
            elif isinstance(data, str):
                try:
                    image_bytes = base64.b64decode(data, validate=True)
                    logging.info("inline_data.data successfully decoded as base64.")
                except Exception as e:
                    logging.warning(
                        "inline_data.data is str but not valid base64: %s. "
                        "Using raw bytes via latin1 encoding.",
                        e,
                    )
                    image_bytes = data.encode("latin1")
            else:
                # Fallback: cast to str, then try base64
                s = str(data)
                try:
                    image_bytes = base64.b64decode(s, validate=True)
                    logging.info(
                        "inline_data.data (non-typical type) decoded as base64 from str()."
                    )
                except Exception as e:
                    logging.warning(
                        "inline_data.data has unexpected type and cannot be decoded as base64: %s. "
                        "Using raw string bytes.",
                        e,
                    )
                    image_bytes = s.encode("latin1")

            # Try to open as an image
            try:
                img = PILImage.open(BytesIO(image_bytes))
                img.load()
                logging.info("Image generation completed successfully.")
                return img
            except Exception as e:
                logging.error("PIL failed to identify image file: %s", e)
                # Try the next part if any
                continue

        # If none of the parts could be decoded as an image
        raise RuntimeError(
            f"Could not decode any inline_data as an image. Parts: {parts}"
        )

    except Exception as e:
        logging.error("Error during Gemini image generation: %s", e)
        raise


# ======================================
# Streamlit UI
# ======================================
st.set_page_config(
    page_title="Voice → Image (AssemblyAI + Bytez + Gemini)",
    page_icon="🎨",
)

# Initialize session state keys
for key, default in [
    ("audio_dict", None),
    ("transcript", None),
    ("prompt", None),
    ("image", None),
    ("last_audio_hash", None),
    ("last_request_time", 0.0),
]:
    if key not in st.session_state:
        st.session_state[key] = default

# ======================================
# Central part of UI
# ======================================
st.title("🎨 Voice to Image — AssemblyAI + Bytez + Gemini")
st.caption("Record your voice, then generate an image from it.")

# 1) Recording
st.markdown("### 1. Recording")

# Get current recording from session
audio_dict = st.session_state.audio_dict

# If we already have audio, show "Start new recording"
record_button_label = "🎙 Start recording" if not audio_dict else "🎙 Start new recording"

new_audio_dict = mic_recorder(
    start_prompt=record_button_label,
    stop_prompt="🛑 Stop recording",
    format="wav",
    key="recorder",
)

# If we received a fresh recording, store it in session
if new_audio_dict and isinstance(new_audio_dict, dict) and new_audio_dict.get("bytes"):
    st.session_state.audio_dict = new_audio_dict
    audio_dict = new_audio_dict

audio_bytes = None
if audio_dict and isinstance(audio_dict, dict) and audio_dict.get("bytes"):
    audio_bytes = audio_dict["bytes"]
    st.audio(audio_bytes, format="audio/wav")

# 2) Generate image
st.markdown("### 2. Generate image")

can_send = audio_bytes is not None and (
    time.time() - st.session_state.last_request_time > 3
)

if st.button("✨ Generate image", disabled=audio_bytes is None):
    if audio_bytes is None:
        st.warning("Please record audio first.")
    elif not can_send:
        st.warning("Please wait a few seconds before sending another request.")
    else:
        audio_hash = hashlib.sha256(audio_bytes).hexdigest()

        if (
            audio_hash == st.session_state.last_audio_hash
            and st.session_state.prompt
            and st.session_state.image is not None
        ):
            st.info("This audio was already processed. Showing cached results.")
            logging.info(
                "Re-used cached transcript + prompt + image for the same audio."
            )
        else:
            try:
                # 1) STT
                with st.spinner("Transcribing audio with AssemblyAI..."):
                    transcript = transcribe_with_assemblyai(audio_bytes)
                    st.session_state.transcript = transcript
                    logging.info("Final transcript: %s", transcript)

                # 2) LLM prompt (Bytez)
                with st.spinner("Generating image prompt with Bytez..."):
                    prompt = build_image_prompt_with_bytez(transcript)
                    st.session_state.prompt = prompt
                    logging.info("Final prompt (Bytez): %s", prompt)

                # 3) Image (Gemini)
                with st.spinner("Generating image with Gemini..."):
                    image = generate_image_with_gemini(prompt)
                    st.session_state.image = image
                    logging.info("Image stored in session_state.")

                st.session_state.last_audio_hash = audio_hash
                st.session_state.last_request_time = time.time()

                st.success(
                    "Done! Check the generated image below and details in the sidebar."
                )

            except Exception as e:
                st.error(f"Error in pipeline: {e}")
                logging.error(
                    "Voice→Text→Prompt→Image pipeline error: %s",
                    e,
                )

# 3) Show result image in the center
st.markdown("### 3. Result image")
if st.session_state.image is not None:
    st.image(
        st.session_state.image,
        caption="Image generated by Gemini from your voice prompt",
        use_container_width=True,
    )
else:
    st.info("No image yet. Record your voice and click **Generate image**.")


# ======================================
# Sidebar with metadata
# ======================================
with st.sidebar:
    st.title("ℹ️ Session info")

    st.markdown("### Models in use")
    st.markdown("- STT: **AssemblyAI**")
    st.markdown("- LLM: **Bytez – openai/gpt-4o-mini**")
    st.markdown("- Image: **Google Gemini – gemini-2.5-flash-image**")

    st.markdown("---")
    st.markdown("### 🎧 Transcript")
    if st.session_state.transcript:
        st.write(st.session_state.transcript)
    else:
        st.caption("No transcript yet. Record and generate an image.")

    st.markdown("### 🧠 Image prompt")
    if st.session_state.prompt:
        st.write(st.session_state.prompt)
    else:
        st.caption("No image prompt yet. It will appear after processing.")
