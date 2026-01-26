"""LLM configuration: model settings and prompts."""

# Model configuration
DEFAULT_MODEL = "gemma-3-1b-it"

# Rate limit settings
MAX_RETRIES = 5
BASE_DELAY = 10  # seconds
MAX_DELAY = 120  # seconds

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
    "Exclude: jokes, complaints about job searching, news articles about academia, "
    "personal announcements (like someone accepting a position), or general discussions. "
    "Answer only YES or NO."
)

DISCIPLINE_PROMPT_TEMPLATE = (
    "Classify this academic job posting into one of these disciplines: {disciplines}. "
    "Answer with just the discipline name, nothing else."
)
