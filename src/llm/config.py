"""LLM configuration: model settings and prompts."""

# Model configuration
DEFAULT_MODEL = "gemma-3-1b-it"

# Rate limit settings
MAX_RETRIES = 5
BASE_DELAY = 10  # seconds (initial backoff on rate limit)
MAX_DELAY = 120  # seconds (max backoff)
REQUEST_COOLDOWN = 2  # seconds between requests (free tier: 30 req/min = 2s)

# Academic disciplines for classification
DISCIPLINES = [
    "Computer Science",
    "Biology",
    "Chemistry & Materials Science",
    "Physics",
    "Mathematics",
    "Medicine",
    "Psychology",
    "Economics",
    "Linguistics",
    "History",
    "Sociology & Political Science",
    "Arts & Humanities",
    "Education",
    "Other",
    "General call",
]

# Prompts
IS_REAL_JOB_PROMPT = (
    "Is this a real PhD or academic job posting? "
    "A real job posting should advertise an actual position with application details. "
    "Exclude: jokes, complaints about job searching, news articles about academia, summer schools, awards, "
    "personal announcements (like someone accepting a position), or general discussions. "
    "Answer only YES or NO."
)

DISCIPLINE_PROMPT_TEMPLATE = (
    "Classify this academic job posting into 1-3 disciplines from this list: {disciplines}. "
    "If it spans multiple fields, list all that apply (comma-separated, max 3). "
    "For example bioinformatics should be both Biology and Computer Science. "
    "If it's a university-wide program, use 'General call'. "
    "Answer with discipline names only, nothing else."
)
