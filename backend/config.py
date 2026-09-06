"""
Nexus — Configuration
Loads all environment variables and defines application constants.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ─── Supabase ───
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")
# Shared JWT secret — enables fast local token verification (skips the per-request
# Supabase Auth round-trip). If unset, auth falls back to supabase.auth.get_user().
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET", "")

# ─── Groq ───
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
# Groq retired the Llama chat models; gpt-oss is the current general-purpose tier.
# Override via env when the catalog changes again.
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
# gpt-oss is a reasoning model: it spends completion tokens thinking before it
# emits any content, so low-max_tokens calls come back empty at the default
# effort. "low" keeps thinking to ~20 tokens and fits our existing budgets.
GROQ_REASONING_EFFORT = os.getenv("GROQ_REASONING_EFFORT", "low")
# Vision-capable model (override via env if Groq's catalog changes).
GROQ_VISION_MODEL = os.getenv("GROQ_VISION_MODEL", "")

# ─── Tavily ───
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")

# ─── Embeddings ───
EMBED_MODEL = "embed-english-light-v3.0"
EMBED_DIMENSIONS = 384

# ─── Chunking ───
CHUNK_SIZE = 2500
CHUNK_OVERLAP = 200

# ─── Retrieval ───
TOP_K = 5
# Permissive pre-filter before reranking; tune via env without a code change.
SIMILARITY_THRESHOLD = float(os.getenv("SIMILARITY_THRESHOLD", "0.10"))

# ─── File Upload ───
MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "20"))
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
ALLOWED_EXTENSIONS = [".pdf", ".txt", ".md", ".csv", ".docx", ".pptx", ".xlsx", ".xls"]

# ─── Storage ───
STORAGE_BUCKET = "documents"

# ─── App ───
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173").split(",")
