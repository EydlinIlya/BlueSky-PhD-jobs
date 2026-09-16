"""LLM configuration: model settings and prompts."""

import os

# Primary Mistral model and optional fallback-provider models.
# Override any of them without changing application code.
MISTRAL_MODEL = os.environ.get("MISTRAL_MODEL", "ministral-14b-latest")
MISTRAL_MAX_COMPLETION_TOKENS = 256
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemma-4-31b-it")
NVIDIA_MODEL = os.environ.get("NVIDIA_MODEL", "google/gemma-4-31b-it")
NVIDIA_MAX_COMPLETION_TOKENS = 512
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
GROQ_MAX_COMPLETION_TOKENS = 512
GROQ_REQUEST_COOLDOWN = 15  # max 4 requests/minute for Groq's 8k free-plan TPM

# Rate limit settings
MAX_RETRIES = 5        # retries for rate limits / transient errors
MAX_TIMEOUT_RETRIES = 4  # retries for network timeouts (API may be down)
BASE_DELAY = 10  # seconds (initial backoff on rate limit)
MAX_DELAY = 120  # seconds (max backoff)
REQUEST_COOLDOWN = 12  # seconds between requests; conservative for 14k TPM quota
REQUEST_TIMEOUT = 30  # seconds to wait for a single API response

# Academic disciplines for classification
DISCIPLINES = [
    "Computer Science",
    "Biology",
    "Ecology",
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
    "Decide if this social media post is sharing an academic job/position opening "
    "that people can currently apply to.\n\n"
    "YES — the post advertises an open position (even briefly, even if details "
    "are in an external link, even if it's part of a thread):\n"
    "- 'PhD position available in my lab at Durham! Email me for details.' → YES\n"
    "- 'Open postdoc in movement ecology - Deadline Feb 15' → YES\n"
    "- 'We have a PhD studentship opportunity, closing date 20th Feb' → YES\n"
    "- 'We will be hiring 14 PhD researchers next month' → YES\n"
    "- 'The second position is at Exeter, includes salary and PhD fees' → YES\n"
    "- 'There's also a PhD position: www.jobbnorge.no/...' → YES\n"
    "- 'Postdoc Position in Psychology at University of Cologne, deadline Feb 15' → YES\n"
    "- 'Assistant Professor (tenure-track) in Computational Biology at MIT' → YES\n\n"
    "NO — the post does NOT advertise a currently open position:\n"
    "- 'PhD position noted, deadline 23 Feb' → NO (commenting on someone else's post)\n"
    "- 'Yes, my understanding is that a PhD is required' → NO (answering a question)\n"
    "- 'Stay tuned, we will be opening positions soon' → NO (future, not open yet)\n"
    "- 'Oops forgot to tag my job advert with hashtags' → NO (references another post)\n"
    "- 'In Sweden a PhD position is a job' → NO (general discussion)\n"
    "- 'Supported PhD students with their studies' → NO (activity summary)\n"
    "- 'Congratulations to Dr. Smith on completing her PhD!' → NO\n"
    "- 'Join our advisory panel for early career researchers' → NO (not a research position)\n"
    "- 'PhD students, join our innovation call for projects!' → NO (grant/contest, not a job)\n"
    "- 'I'm scouting students for potential opportunities' → NO (expression of interest)\n"
    "- 'Call for study participation for undergrad/master students' → NO (study, not a job)\n"
    "- 'Enrolled students, apply for our library fellowship' → NO (student award, not a position)\n"
    "- 'We have a job opening for a program officer' → NO (admin role, not academic research)\n"
    "- 'Full Professor of Biology at University of Oxford' → NO (senior faculty, not early-career)\n"
    "- 'Associate Professor / Full Professor position in Chemistry' → NO (senior faculty)\n"
    "- 'Visiting Professor in Economics for 2026-27' → NO (senior faculty)\n"
    "- 'Director of Institute for Global Food Security' → NO (senior leadership, not research position)\n\n"
    "Answer YES only if the post shares or advertises an early-career academic research position "
    "(PhD, postdoc, research assistant, assistant professor) that is currently open. "
    "Senior faculty positions (Associate Professor, Full Professor, Professor, Director, Chair) are NO. "
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
    '  "position_type": array of position types from: PhD Student, Postdoc, Master Student, Research Assistant\n'
    '  "job_title": exact advertised role title, or null\n'
    '  "hiring_organization": exact hiring university, institute, or company, or null\n'
    '  "application_url": exact HTTP(S) application or official vacancy URL, or null\n'
    '  "application_deadline": exact deadline as YYYY-MM-DD, or null\n'
    '  "location_text": exact city/region/campus wording, or null\n\n'
    "EVIDENCE rules for the five job fields:\n"
    "- Copy facts only when they are explicitly present in the post or linked-page preview.\n"
    "- Never infer an employer from the author's handle or bio.\n"
    "- Never invent or normalize a vague role into a more specific job title.\n"
    "- application_url must be an explicit application/official vacancy URL, never a Bluesky URL.\n"
    "- A month/day without an unambiguous year is not an exact deadline; return null.\n"
    "- Return null for every uncertain or missing value.\n\n"
    "DISCIPLINE rules:\n"
    "- Pick 1-3 that best match. For cross-disciplinary work, list all (e.g., bioinformatics = Biology + Computer Science).\n"
    "- Remote sensing of forests, vegetation, crop fields, or ecosystems = Ecology (primary). "
    "Biology and/or Computer Science may be listed as SECONDARY tags only if the post also "
    "explicitly involves biological methods or ML/algorithm research. Do not mark such posts "
    "as Biology-primary or Computer Science-primary.\n"
    "- If it's a university-wide program, use 'General call'.\n\n"
    "COUNTRY rules:\n"
    "- Use standard country names: USA, UK, Germany, France, Switzerland, etc.\n"
    "- Identify country from university names, domains, or city names.\n"
    "- If not determinable, use 'Unknown'.\n\n"
    "POSITION TYPE rules:\n"
    "- PhD Student: any doctoral/PhD position (including 'PhD Position', 'Doctoral Researcher', 'predoctoral')\n"
    "- Postdoc: postdoctoral position, research fellow, or any role that REQUIRES a PhD/doctorate, "
    "OR an Assistant Professor / tenure-track faculty position\n"
    "- Master Student: master's thesis or MSc position\n"
    "- Research Assistant: lab assistant, research aide, RA position (non-doctoral)\n"
    "- If the post advertises multiple types, list all that apply (e.g., [\"PhD Student\", \"Postdoc\"])\n"
    "- NEVER output 'PhD Student' for a full/associate/visiting professor or director role — "
    "those should not reach this step\n\n"
    "Examples:\n"
    'Input: "PhD position at University of Oxford in computational biology"\n'
    'Output: {{"disciplines": ["Biology", "Computer Science"], "country": "UK", "position_type": ["PhD Student"], "job_title": "PhD position in computational biology", "hiring_organization": "University of Oxford", "application_url": null, "application_deadline": null, "location_text": "Oxford"}}\n\n'
    'Input: "Postdoc and PhD positions at MIT in physics"\n'
    'Output: {{"disciplines": ["Physics"], "country": "USA", "position_type": ["PhD Student", "Postdoc"], "job_title": null, "hiring_organization": "MIT", "application_url": null, "application_deadline": null, "location_text": null}}\n\n'
    'Input: "Doctoral Research Position at Friedrich-Schiller-Universitat Jena in archaeology"\n'
    'Output: {{"disciplines": ["History"], "country": "Germany", "position_type": ["PhD Student"], "job_title": "Doctoral Research Position in archaeology", "hiring_organization": "Friedrich Schiller University Jena", "application_url": null, "application_deadline": null, "location_text": "Jena"}}\n\n'
    'Input: "Research assistant at Aarhus University, Denmark in microbial biology"\n'
    'Output: {{"disciplines": ["Biology"], "country": "Denmark", "position_type": ["Research Assistant"], "job_title": "Research assistant", "hiring_organization": "Aarhus University", "application_url": null, "application_deadline": null, "location_text": null}}\n\n'
    'Input: "MS opportunity in machine learning, apply via link"\n'
    'Output: {{"disciplines": ["Computer Science"], "country": "Unknown", "position_type": ["Master Student"], "job_title": "MS opportunity in machine learning", "hiring_organization": null, "application_url": null, "application_deadline": null, "location_text": null}}\n\n'
    'Input: "Hiring one postdoctoral and two predoctoral researchers in neuroscience"\n'
    'Output: {{"disciplines": ["Psychology"], "country": "Unknown", "position_type": ["PhD Student", "Postdoc"], "job_title": null, "hiring_organization": null, "application_url": null, "application_deadline": null, "location_text": null}}\n\n'
    'Input: "Assistant Professor (tenure-track) in Computational Biology at MIT"\n'
    'Output: {{"disciplines": ["Biology", "Computer Science"], "country": "USA", "position_type": ["Postdoc"], "job_title": "Assistant Professor (tenure-track) in Computational Biology", "hiring_organization": "MIT", "application_url": null, "application_deadline": null, "location_text": null}}\n\n'
    'Input: "PhD position in satellite remote sensing of boreal forest carbon dynamics, University of Helsinki"\n'
    'Output: {{"disciplines": ["Ecology", "Computer Science"], "country": "Finland", "position_type": ["PhD Student"], "job_title": "PhD position in satellite remote sensing of boreal forest carbon dynamics", "hiring_organization": "University of Helsinki", "application_url": null, "application_deadline": null, "location_text": null}}\n\n'
    "Return ONLY the JSON object, no other text."
)
