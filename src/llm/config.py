"""LLM configuration: model settings and prompts."""

# Model configuration
DEFAULT_MODEL = "meta/llama-4-maverick-17b-128e-instruct"

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
    "Decide if this social media post is sharing an academic job/position opening.\n\n"
    "Examples:\n"
    "- 'PhD position available in my lab at Durham! Email me for details.' → YES\n"
    "- 'Open postdoc position in movement ecology - Deadline Feb 15' → YES\n"
    "- 'We have a PhD studentship opportunity, closing date 20th Feb' → YES\n"
    "- 'We will be hiring 14 PhD researchers next month' → YES\n"
    "- 'So tired of applying to PhD positions with no response' → NO\n"
    "- 'Congratulations to Dr. Smith on completing her PhD!' → NO\n"
    "- 'Interesting article about the state of academic hiring' → NO\n"
    "- 'Join our advisory panel for early career researchers' → NO\n\n"
    "Answer YES if the post shares/advertises an open position (even briefly, "
    "even if details are in an external link). "
    "Answer NO if it's not advertising a position. "
    "Answer only YES or NO."
)

DISCIPLINE_PROMPT_TEMPLATE = (
    "Classify this academic job posting into 1-3 disciplines from this list: {disciplines}. "
    "If it spans multiple fields, list all that apply (comma-separated, max 3). "
    "For example bioinformatics should be both Biology and Computer Science. "
    "If it's a university-wide program, use 'General call'. "
    "Answer with discipline names only, nothing else."
)
