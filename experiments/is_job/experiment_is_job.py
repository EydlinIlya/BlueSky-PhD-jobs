"""Experiment: Compare IS_REAL_JOB_PROMPT variants on curated test set.

Tests whether an improved prompt can correctly reject false positives
(comments, future announcements, general discussion) while still accepting
true job postings — including those posted as replies/threads.

Uses NVIDIA Llama 4 Maverick (same model as production).
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
load_dotenv()

from src.llm.nvidia import NvidiaProvider, DEFAULT_NVIDIA_MODEL
from src.llm.config import IS_REAL_JOB_PROMPT

# ── Prompt variants ──────────────────────────────────────────────────────────

PROMPTS = {
    "v1_current": IS_REAL_JOB_PROMPT,

    "v2_improved": (
        "Decide if this social media post is sharing an academic job/position opening "
        "that people can currently apply to.\n\n"
        "YES examples (the post shares/advertises an open position):\n"
        "- 'PhD position available in my lab at Durham! Email me for details.' → YES\n"
        "- 'Open postdoc position in movement ecology - Deadline Feb 15' → YES\n"
        "- 'We have a PhD studentship opportunity, closing date 20th Feb' → YES\n"
        "- 'We will be hiring 14 PhD researchers next month' → YES\n"
        "- 'The second position is at Exeter, includes salary and PhD fees for 3.5 years' → YES\n"
        "- 'There's also a PhD position: www.jobbnorge.no/...' → YES\n\n"
        "NO examples (NOT advertising a currently open position):\n"
        "- 'PhD position noted, deadline 23 Feb' → NO (commenting on someone else's post)\n"
        "- 'Yes, my understanding is that a PhD is required' → NO (answering a question)\n"
        "- 'Stay tuned, we will be opening positions soon' → NO (future announcement, not open yet)\n"
        "- 'Oops forgot to tag my job advert with hashtags' → NO (referencing another post, no job info here)\n"
        "- 'In Sweden a PhD position is a job' → NO (general discussion about positions)\n"
        "- 'Supported PhD students with their studies' → NO (activity summary, not a vacancy)\n"
        "- 'Congratulations to Dr. Smith on completing her PhD!' → NO\n"
        "- 'Interesting article about the state of academic hiring' → NO\n"
        "- 'Join our advisory panel for early career researchers' → NO\n"
        "- 'PhD students in 1st year, join our innovation call for projects!' → NO (not a job)\n\n"
        "Answer YES only if the post itself shares or advertises a position that is currently "
        "open for applications (even briefly, even if details are in an external link). "
        "Answer NO if the post merely comments on, discusses, or announces future positions. "
        "Answer only YES or NO."
    ),

    "v3_strict": (
        "Decide if this social media post is sharing an academic job/position opening "
        "that someone can apply to RIGHT NOW.\n\n"
        "Answer YES if ALL of these are true:\n"
        "1. The post advertises a specific position (PhD, postdoc, research assistant, etc.)\n"
        "2. The position is currently open for applications\n"
        "3. The post itself contains enough info to identify the position "
        "(title, institution, link, or how to apply)\n\n"
        "Answer NO if any of these are true:\n"
        "- The post is commenting on or noting someone else's vacancy\n"
        "- The post is answering a question about a job\n"
        "- The post announces positions that will open in the future but aren't open yet\n"
        "- The post references a job advert in another post without including the job details\n"
        "- The post is general discussion about academic positions\n"
        "- The post is an activity summary or congratulations\n"
        "- The post is about a non-research program (training, conference, advisory panel, outreach)\n\n"
        "Examples:\n"
        "- 'PhD position available in my lab - email me for details' → YES\n"
        "- 'Open postdoc in ecology, deadline Feb 15: link.com/apply' → YES\n"
        "- 'The second position is at Exeter, 3.5 years funded: jobs.exeter.ac.uk/...' → YES\n"
        "- 'PhD position noted, deadline 23 Feb' → NO\n"
        "- 'Stay tuned, we will be opening positions soon!' → NO\n"
        "- 'In Sweden a PhD position is a job' → NO\n"
        "- 'Forgot to tag my job advert with hashtags' → NO\n\n"
        "Answer only YES or NO."
    ),

    "v4_balanced": (
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
        "- 'Postdoc Position in Psychology at University of Cologne, deadline Feb 15' → YES\n\n"
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
        "- 'We have a job opening for a program officer' → NO (admin role, not academic research)\n\n"
        "Answer YES only if the post shares or advertises an academic research position "
        "(PhD, postdoc, research assistant, faculty) that is currently open. "
        "Answer NO otherwise. Answer only YES or NO."
    ),
}


def run_prompt(llm, posts, prompt_name, prompt_text):
    """Run one prompt variant against all test posts."""
    print(f"\n{'='*60}")
    print(f"  Running: {prompt_name}")
    print(f"{'='*60}")

    results = []
    for i, post in enumerate(posts):
        text = post["raw_text"]
        for attempt in range(3):
            try:
                resp = llm.classify(text, prompt_text).strip().upper()
                break
            except Exception as e:
                if attempt < 2:
                    print(f"  [{i+1:>2}] Retry {attempt+1} after error: {e}")
                    import time; time.sleep(15)
                else:
                    resp = "ERROR"
        is_job = resp.startswith("YES")
        results.append({"response": resp, "is_job": is_job})
        print(f"  [{i+1:>2}/{len(posts)}] {resp:>3} | {text[:70]}...")

    return results


def evaluate(posts, labels, prompt_results):
    """Compare all prompt variants against ground truth."""
    print(f"\n{'='*80}")
    print("  RESULTS")
    print(f"{'='*80}")

    for pname, results in prompt_results.items():
        tp = fp = tn = fn = 0
        errors = []

        for i, (post, label, pred) in enumerate(zip(posts, labels, results)):
            expected = label["is_job"]
            predicted = pred["is_job"]

            if expected and predicted:
                tp += 1
            elif not expected and not predicted:
                tn += 1
            elif not expected and predicted:
                fp += 1
                errors.append((i + 1, "FP", post["raw_text"][:60], label["notes"]))
            else:
                fn += 1
                errors.append((i + 1, "FN", post["raw_text"][:60], label["notes"]))

        total = len(posts)
        accuracy = (tp + tn) / total
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

        print(f"\n--- {pname} ---")
        print(f"  Accuracy:  {accuracy:.1%} ({tp + tn}/{total})")
        print(f"  Precision: {precision:.1%}  (TP={tp}, FP={fp})")
        print(f"  Recall:    {recall:.1%}  (TP={tp}, FN={fn})")
        print(f"  F1:        {f1:.1%}")
        print(f"  TN={tn}")

        if errors:
            print(f"\n  Errors:")
            for idx, kind, text, notes in errors:
                print(f"    [{idx:>2}] {kind}: {text}...")
                print(f"          {notes}")


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))

    with open(os.path.join(script_dir, "test_posts.json"), encoding="utf-8") as f:
        posts = json.load(f)
    with open(os.path.join(script_dir, "manual_labels.json"), encoding="utf-8") as f:
        labels = json.load(f)

    assert len(posts) == len(labels), f"Mismatch: {len(posts)} posts vs {len(labels)} labels"

    num_positive = sum(1 for l in labels if l["is_job"])
    num_negative = sum(1 for l in labels if not l["is_job"])
    print(f"Loaded {len(posts)} test posts: {num_positive} positive, {num_negative} negative")

    # Load cached results
    results_path = os.path.join(script_dir, "experiment_results.json")
    prev_results = {}
    if os.path.exists(results_path):
        with open(results_path, encoding="utf-8") as f:
            prev_data = json.load(f)
            prev_results = prev_data.get("prompt_results", {})

    api_key = os.environ.get("NVIDIA_API_KEY")
    if not api_key:
        print("ERROR: NVIDIA_API_KEY not set")
        sys.exit(1)

    llm = NvidiaProvider(api_key, model=DEFAULT_NVIDIA_MODEL)

    prompt_results = {}
    for name, prompt_text in PROMPTS.items():
        if name in prev_results and len(prev_results[name]) == len(posts):
            print(f"\n  Reusing cached results for {name}")
            prompt_results[name] = prev_results[name]
        else:
            prompt_results[name] = run_prompt(llm, posts, name, prompt_text)

    # Evaluate
    evaluate(posts, labels, prompt_results)

    # Save results
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump({
            "num_posts": len(posts),
            "num_positive": num_positive,
            "num_negative": num_negative,
            "prompt_results": prompt_results,
        }, f, indent=2, ensure_ascii=False)
    print(f"\nSaved to {results_path}")


if __name__ == "__main__":
    main()
