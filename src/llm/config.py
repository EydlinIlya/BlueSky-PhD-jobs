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

# Position types for classification
POSITION_TYPES = [
    "PhD Student",
    "Postdoc",
    "Master Student",
    "Research Assistant",
]

METADATA_PROMPT_TEMPLATE = (
    "Extract metadata from this academic job posting as JSON.\n\n"
    "Return a JSON object with these fields:\n"
    '  "disciplines": array of 1-3 disciplines from this list: {disciplines}\n'
    '  "country": country where the position is located (standard name, or "Unknown")\n'
    '  "position_type": array of position types from: PhD Student, Postdoc, Master Student, Research Assistant\n\n'
    "DISCIPLINE rules:\n"
    "- Pick 1-3 that best match. For cross-disciplinary work, list all (e.g., bioinformatics = Biology + Computer Science).\n"
    "- If it's a university-wide program, use 'General call'.\n\n"
    "COUNTRY rules:\n"
    "- Use standard country names: USA, UK, Germany, France, Switzerland, etc.\n"
    "- Identify country from university names, domains, or city names.\n"
    "- If not determinable, use 'Unknown'.\n\n"
    "POSITION TYPE rules:\n"
    "- PhD Student: any doctoral/PhD position (including 'PhD Position', 'Doctoral Researcher', 'predoctoral')\n"
    "- Postdoc: postdoctoral position, research fellow, or any role that REQUIRES a PhD/doctorate\n"
    "- Master Student: master's thesis or MSc position\n"
    "- Research Assistant: lab assistant, research aide, RA position (non-doctoral)\n"
    "- If the post advertises multiple types, list all that apply (e.g., [\"PhD Student\", \"Postdoc\"])\n\n"
    "Examples:\n"
    'Input: "PhD position at University of Oxford in computational biology"\n'
    'Output: {{"disciplines": ["Biology", "Computer Science"], "country": "UK", "position_type": ["PhD Student"]}}\n\n'
    'Input: "Postdoc and PhD positions at MIT in physics"\n'
    'Output: {{"disciplines": ["Physics"], "country": "USA", "position_type": ["PhD Student", "Postdoc"]}}\n\n'
    'Input: "Doctoral Research Position at Friedrich-Schiller-Universitat Jena in archaeology"\n'
    'Output: {{"disciplines": ["History"], "country": "Germany", "position_type": ["PhD Student"]}}\n\n'
    'Input: "Research assistant at Aarhus University, Denmark in microbial biology"\n'
    'Output: {{"disciplines": ["Biology"], "country": "Denmark", "position_type": ["Research Assistant"]}}\n\n'
    'Input: "MS opportunity in machine learning, apply via link"\n'
    'Output: {{"disciplines": ["Computer Science"], "country": "Unknown", "position_type": ["Master Student"]}}\n\n'
    'Input: "Hiring one postdoctoral and two predoctoral researchers in neuroscience"\n'
    'Output: {{"disciplines": ["Psychology"], "country": "Unknown", "position_type": ["PhD Student", "Postdoc"]}}\n\n'
    "Return ONLY the JSON object, no other text."
)
