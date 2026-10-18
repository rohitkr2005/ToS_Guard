import os
import json
import re
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify, render_template, send_from_directory
from dotenv import load_dotenv

# Load environment variables strictly from .env
load_dotenv()

import threading
import time

app = Flask(__name__, static_folder="static")

def start_keep_alive_worker():
    """Background worker that pings the /health endpoint every 8 minutes to prevent Render from sleeping."""
    def pinger():
        time.sleep(30)
        interval = int(os.getenv("PING_INTERVAL_SECONDS", 480))
        while True:
            # Render automatically injects RENDER_EXTERNAL_URL (e.g. https://tos-guard.onrender.com)
            target_base = os.getenv("RENDER_EXTERNAL_URL") or os.getenv("SELF_PING_URL")
            if not target_base:
                custom_domain = os.getenv("CUSTOM_DOMAIN")
                if custom_domain and custom_domain != "tosguard.com":
                    target_base = "https://" + custom_domain if not custom_domain.startswith(("http://", "https://")) else custom_domain

            if target_base:
                target_url = target_base.rstrip("/") + "/health"
                try:
                    resp = requests.get(target_url, timeout=15)
                    print(f"[Keep-Alive] Successfully pinged {target_url} -> HTTP {resp.status_code}")
                except Exception as e:
                    print(f"[Keep-Alive] Ping warning: {e}")
            else:
                print("[Keep-Alive] Standing by: RENDER_EXTERNAL_URL will activate once deployed on Render.")

            # Render free tier spins down after 15 minutes of inactivity; 8 minutes (480s) ensures it stays awake
            time.sleep(interval)

    t = threading.Thread(target=pinger, daemon=True)
    t.start()

# Initialize keep-alive daemon on startup (works with both local run and Gunicorn on Render)
start_keep_alive_worker()

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
import hashlib

# In-memory deterministic analysis cache (SHA-256)
ANALYSIS_CACHE = {}

# Primary free model with active verified free fallbacks
FREE_MODELS = [
    "nvidia/nemotron-3-super-120b-a12b:free",
    "nvidia/nemotron-3.5-super-vl:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free"
]

CUSTOM_DOMAIN = os.getenv("CUSTOM_DOMAIN", "tosguard.com")

# Deterministic NLP Legal Pattern Matchers
LEGAL_REGEX_SIGNALS = {
    "arbitration": [
        (re.compile(r"\b(binding\s+arbitration|private\s+arbitration|arbitrator)\b", re.I), "Binding Arbitration"),
        (re.compile(r"\b(class\s+action\s+waiver|waive.*class\s+action|representative\s+action)\b", re.I), "Class Action Waiver"),
        (re.compile(r"\b(waive.*jury\s+trial|trial\s+by\s+jury)\b", re.I), "Jury Trial Waiver")
    ],
    "auto_renewal": [
        (re.compile(r"\b(automatically\s+renew|automatic\s+renewal|recurring\s+billing)\b", re.I), "Automatic Renewal"),
        (re.compile(r"\b(without\s+prior\s+notice|without\s+notice)\b", re.I), "No Renewal Notice"),
        (re.compile(r"\b(non-refundable|no\s+refunds)\b", re.I), "Strict No-Refund")
    ],
    "data_selling": [
        (re.compile(r"\b(sell|monetize|commercial\s+broker|data\s+broker)\b", re.I), "Data Commercialization"),
        (re.compile(r"\b(targeted\s+advertising|third-party\s+ad\s+network)\b", re.I), "Third-Party Ad Tracking"),
        (re.compile(r"\b(geolocation\s+tracking|browsing\s+habits)\b", re.I), "Behavioral Profiling")
    ],
    "content_ownership": [
        (re.compile(r"\b(perpetual|irrevocable)\b", re.I), "Perpetual License"),
        (re.compile(r"\b(worldwide|royalty-free|sublicensable)\b", re.I), "Worldwide Royalty-Free"),
        (re.compile(r"\b(derivative\s+works|commercialize\s+your\s+content)\b", re.I), "Derivative Commercial Rights")
    ],
    "account_deletion": [
        (re.compile(r"\b(retain.*indefinitely|retained\s+indefinitely|survive\s+termination)\b", re.I), "Indefinite Data Retention"),
        (re.compile(r"\b(terminate.*without\s+notice|sole\s+discretion)\b", re.I), "Arbitrary Account Termination")
    ]
}


def scan_rule_based_signals(text: str) -> dict:
    """Deterministic NLP regex scanning for statutory legal terms."""
    matches = {}
    for cat, rules in LEGAL_REGEX_SIGNALS.items():
        found = []
        for pattern, label in rules:
            if pattern.search(text):
                found.append(label)
        matches[cat] = found
    return matches


SYSTEM_PROMPT = """You are ToS Guard, an automated contract intelligence and consumer rights advisor.
Analyze the provided Terms of Service or Privacy Policy text for unfair clauses and consumer risk.

You MUST assess risk across exactly these 5 categories:
1. data_selling: Personal data harvesting, tracking, commercialization, sharing with 3rd-party advertisers/brokers.
2. auto_renewal: Tricky subscription renewals, lack of cancellation reminders, hidden recurring fees, no refund policies.
3. arbitration: Forced binding arbitration, surrender of jury trial rights, class-action lawsuit waivers.
4. content_ownership: Provider claiming broad, irrevocable, royalty-free licenses to user-generated content or IP.
5. account_deletion: Barriers to terminating account, indefinite retention of user files/data post-deletion, ignoring deletion requests.

SCORING RULES (0-100 for each category):
- 0 to 39: Low Risk (Clear, fair, consumer-protective)
- 40 to 69: Moderate Risk (Standard but slightly restrictive or ambiguous)
- 70 to 100: High/Severe Risk (Predatory, hostile, aggressive waivers, or extensive data selling)

OUTPUT REQUIREMENTS:
- You must return ONLY a valid, raw JSON object.
- Do NOT include markdown code blocks (no ```json), commentary, or extra text.
- Do NOT use em dashes. Use hyphens or colons instead.
- For every category, provide:
  - score: integer 0-100
  - summary: strictly ONE short, simple, plain-English sentence
  - detected_clause: the exact verbatim quote (1-2 sentences) from the provided text that triggered this score, or "No high-risk clause found" if score is low
  - legal_tags: an array of 2 to 3 short terminology tags (e.g. ["Class Action Waiver", "Forced Arbitration"])

The JSON MUST strictly follow this structure:
{
  "overall_risk_score": <number 0-100>,
  "overall_summary": "<One concise sentence summarizing the total risk profile>",
  "categories": {
    "data_selling": {
      "name": "Data Selling",
      "score": <number 0-100>,
      "summary": "<One short, simple sentence>",
      "detected_clause": "<Verbatim excerpt from text or 'No high-risk clause found'>",
      "legal_tags": ["<tag1>", "<tag2>"]
    },
    "auto_renewal": {
      "name": "Auto-Renewal",
      "score": <number 0-100>,
      "summary": "<One short, simple sentence>",
      "detected_clause": "<Verbatim excerpt from text or 'No high-risk clause found'>",
      "legal_tags": ["<tag1>", "<tag2>"]
    },
    "arbitration": {
      "name": "Arbitration",
      "score": <number 0-100>,
      "summary": "<One short, simple sentence>",
      "detected_clause": "<Verbatim excerpt from text or 'No high-risk clause found'>",
      "legal_tags": ["<tag1>", "<tag2>"]
    },
    "content_ownership": {
      "name": "Content Ownership",
      "score": <number 0-100>,
      "summary": "<One short, simple sentence>",
      "detected_clause": "<Verbatim excerpt from text or 'No high-risk clause found'>",
      "legal_tags": ["<tag1>", "<tag2>"]
    },
    "account_deletion": {
      "name": "Account Deletion",
      "score": <number 0-100>,
      "summary": "<One short, simple sentence>",
      "detected_clause": "<Verbatim excerpt from text or 'No high-risk clause found'>",
      "legal_tags": ["<tag1>", "<tag2>"]
    }
  }
}
"""


def extract_text_from_url(url: str) -> str:
    """Fetch webpage and extract clean textual content, stripping markup and boilerplate."""
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    }

    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        raise ValueError(f"Could not load webpage: {str(e)}")

    soup = BeautifulSoup(resp.text, "html.parser")
    
    # Remove irrelevant and non-content elements
    for element in soup(["script", "style", "nav", "header", "footer", "noscript", "svg", "form", "button"]):
        element.decompose()

    # Prefer main article container if available
    main_content = soup.find("main") or soup.find("article") or soup.find(id=re.compile(r"content|terms|legal|privacy", re.I)) or soup.body
    
    if not main_content:
        text = soup.get_text(separator=" ")
    else:
        text = main_content.get_text(separator=" ")

    clean_text = re.sub(r"\s+", " ", text).strip()
    return clean_text


def compute_simplified_metrics(text: str) -> dict:
    """Compute clear, easy-to-understand reading metrics for regular consumers."""
    words = [w.strip() for w in re.findall(r"\b[A-Za-z0-9'-]+\b", text) if len(w.strip()) > 0]
    num_words = max(1, len(words))
    sentences = [s.strip() for s in re.split(r"[.!?]+", text) if len(s.strip()) > 3]
    num_sentences = max(1, len(sentences))

    # Average sentence length
    avg_sentence_len = num_words / num_sentences

    # Estimated read time (standard 200 words per minute)
    read_minutes = max(1, round(num_words / 200))

    # Plain English difficulty classification
    if avg_sentence_len < 15:
        difficulty_label = "Easy to Read"
        difficulty_desc = "Short sentences and straightforward language."
    elif avg_sentence_len < 24:
        difficulty_label = "Standard Language"
        difficulty_desc = "Typical commercial language with moderate sentence length."
    elif avg_sentence_len < 32:
        difficulty_label = "Dense Legal Text"
        difficulty_desc = "Long legal sentences that require careful attention."
    else:
        difficulty_label = "Heavy Legalese"
        difficulty_desc = "Extremely long, convoluted clauses designed to obfuscate meaning."

    return {
        "word_count": f"{num_words:,}",
        "read_time": f"{read_minutes} min read",
        "difficulty_label": difficulty_label,
        "difficulty_desc": difficulty_desc,
        "avg_words_per_sentence": round(avg_sentence_len, 1)
    }


def compute_consumer_verdict(overall_score: int, categories: dict) -> dict:
    """Generate clear, non-technical recommendation on whether to agree to the terms."""
    highest_cat = max(categories.values(), key=lambda c: c.get("score", 0))
    highest_score = highest_cat.get("score", 0)
    highest_name = highest_cat.get("name", "Terms")

    if overall_score <= 35 and highest_score < 65:
        return {
            "status": "safe",
            "badge": "Safe to Agree",
            "headline": "Recommended: Safe to Agree",
            "description": "These terms are consumer-friendly. They do not sell your personal data, do not enforce mandatory arbitration waivers, and allow straightforward account cancellation.",
            "action": "You can comfortably accept these terms."
        }
    elif overall_score <= 65 and highest_score < 80:
        return {
            "status": "caution",
            "badge": "Proceed With Caution",
            "headline": "Caution: Review Before Agreeing",
            "description": f"Contains moderately restrictive conditions, specifically regarding {highest_name.lower()}. While common across tech services, you should be aware of the clauses highlighted below.",
            "action": "Accept only if comfortable with the highlighted clauses. Check your account settings to disable third-party data sharing."
        }
    else:
        return {
            "status": "danger",
            "badge": "Do Not Agree (High Risk)",
            "headline": "Warning: High Consumer Risk",
            "description": f"Not recommended to accept freely. These terms contain aggressive restrictions, including predatory {highest_name.lower()} terms and surrender of key legal rights.",
            "action": "Avoid accepting if possible. If you must use this service, check if there is an option to opt out of arbitration within 30 days."
        }


def clean_json_response(raw_text: str) -> dict:
    """Extract and parse JSON safely from model response text."""
    clean = raw_text.strip()
    if clean.startswith("```"):
        clean = re.sub(r"^```(?:json)?\s*", "", clean)
        clean = re.sub(r"\s*```$", "", clean)
    
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        match = re.search(r"(\{.*\})", clean, re.DOTALL)
        if match:
            return json.loads(match.group(1))
        raise ValueError(f"Unable to parse response as valid JSON: {clean[:200]}")


def validate_and_normalize(data: dict, simple_metrics: dict) -> dict:
    """Normalize categories, scores, verbatim clauses, and consumer verdict."""
    required_keys = ["data_selling", "auto_renewal", "arbitration", "content_ownership", "account_deletion"]
    display_names = {
        "data_selling": "Data Selling",
        "auto_renewal": "Auto-Renewal",
        "arbitration": "Arbitration",
        "content_ownership": "Content Ownership",
        "account_deletion": "Account Deletion"
    }

    if "categories" not in data or not isinstance(data["categories"], dict):
        data["categories"] = {}

    for key in required_keys:
        cat = data["categories"].get(key, {})
        if not isinstance(cat, dict):
            cat = {}
        
        raw_score = cat.get("score", 50)
        try:
            score = max(0, min(100, int(round(float(raw_score)))))
        except (ValueError, TypeError):
            score = 50
        
        summary = cat.get("summary")
        if not summary or not isinstance(summary, str):
            summary = f"No specific high-risk clauses identified regarding {display_names[key].lower()}."
        
        summary = summary.replace("\u2014", "-").replace("\u2013", "-").strip()

        detected_clause = cat.get("detected_clause")
        if not detected_clause or not isinstance(detected_clause, str):
            if score >= 60:
                detected_clause = "Specific restrictive clauses identified in this section."
            else:
                detected_clause = "No aggressive or high-risk clauses detected."
        else:
            detected_clause = detected_clause.replace("\u2014", "-").replace("\u2013", "-").strip()

        legal_tags = cat.get("legal_tags")
        if not legal_tags or not isinstance(legal_tags, list):
            if score >= 70:
                legal_tags = ["High Risk Terms", "Aggressive Clause"]
            elif score >= 40:
                legal_tags = ["Standard Terms"]
            else:
                legal_tags = ["Consumer Friendly"]
        else:
            legal_tags = [str(t).replace("\u2014", "-").replace("\u2013", "-").strip() for t in legal_tags[:3]]

        data["categories"][key] = {
            "name": display_names[key],
            "score": score,
            "summary": summary,
            "detected_clause": detected_clause,
            "legal_tags": legal_tags
        }

    raw_overall = data.get("overall_risk_score")
    if raw_overall is not None:
        try:
            data["overall_risk_score"] = max(0, min(100, int(round(float(raw_overall)))))
        except (ValueError, TypeError):
            scores = [data["categories"][k]["score"] for k in required_keys]
            data["overall_risk_score"] = int(round(sum(scores) / len(scores)))
    else:
        scores = [data["categories"][k]["score"] for k in required_keys]
        data["overall_risk_score"] = int(round(sum(scores) / len(scores)))

    overall_sum = data.get("overall_summary")
    if not overall_sum or not isinstance(overall_sum, str):
        data["overall_summary"] = "Analysis completed across all 5 consumer protection dimensions."
    else:
        data["overall_summary"] = overall_sum.replace("\u2014", "-").replace("\u2013", "-").strip()

    # Simplified readability metrics
    data["reading_metrics"] = simple_metrics

    # Consumer Agreement Verdict
    data["verdict"] = compute_consumer_verdict(data["overall_risk_score"], data["categories"])

    return data


@app.context_processor
def inject_domain_context():
    """Inject domain settings into template rendering."""
    return {
        "custom_domain": os.getenv("CUSTOM_DOMAIN", "tosguard.com"),
        "canonical_base": f"https://{os.getenv('CUSTOM_DOMAIN', 'tosguard.com')}"
    }


@app.route("/")
def index():
    """Serve the ToS Guard contract scanner."""
    return render_template("index.html")


@app.route("/privacy")
def privacy():
    """Serve the Privacy Policy page."""
    return render_template("privacy.html")


@app.route("/terms")
def terms():
    """Serve the Terms and Conditions page."""
    return render_template("terms.html")


@app.route("/favicon.ico")
def favicon():
    """Serve favicon."""
    return send_from_directory(app.static_folder, "favicon.svg", mimetype="image/svg+xml")


@app.route("/health")
def health():
    """Health check endpoint."""
    return jsonify({
        "status": "healthy",
        "service": "ToS Guard",
        "domain": os.getenv("CUSTOM_DOMAIN", "tosguard.com")
    })


@app.route("/analyze", methods=["POST"])
def analyze():
    """Analyze legal text provided either as direct text or extracted from a web URL."""
    payload = request.get_json(silent=True) or {}
    text = payload.get("text", "").strip()
    url = payload.get("url", "").strip()

    # If URL is provided, fetch and extract text from the link
    if url:
        try:
            text = extract_text_from_url(url)
        except Exception as e:
            return jsonify({"error": f"Failed to fetch content from URL: {str(e)}"}), 400

    if not text:
        return jsonify({"error": "Please provide legal text or a valid website link to analyze."}), 400

    if len(text) < 30:
        return jsonify({"error": "The provided text is too short. Please paste at least a paragraph or provide a link to full terms."}), 400

    # Reload environment variables to pick up any changes to .env dynamically
    load_dotenv(override=True)

    # Backend API Key resolution
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key or api_key == "your_openrouter_api_key_here":
        return jsonify({
            "error": "The contract analysis service is currently being configured on the server. Please try again shortly."
        }), 503

    # Deterministic Cache Lookup: ensure identical text always returns identical results
    cache_key = hashlib.sha256(text.strip().lower().encode("utf-8")).hexdigest()
    if cache_key in ANALYSIS_CACHE:
        return jsonify(ANALYSIS_CACHE[cache_key])

    # Run deterministic regex NLP scanner on legal terms
    rule_signals = scan_rule_based_signals(text)

    # Calculate consumer-friendly readability metrics
    simple_metrics = compute_simplified_metrics(text)

    headers = {
        "Authorization": f"Bearer {api_key.strip()}",
        "HTTP-Referer": f"https://{os.getenv('CUSTOM_DOMAIN', 'tosguard.com')}",
        "X-Title": "ToS Guard",
        "Content-Type": "application/json"
    }

    # Cap text length to prevent exceeding token limits
    truncated_text = text[:12000]

    request_body = {
        "model": "nvidia/nemotron-3-super-120b-a12b:free",
        "models": FREE_MODELS,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Analyze this Terms of Service text:\n\n{truncated_text}"}
        ],
        "temperature": 0.0,
        "seed": 42
    }

    try:
        response = requests.post(OPENROUTER_API_URL, headers=headers, json=request_body, timeout=45)
        
        if response.status_code != 200:
            error_data = response.json() if "application/json" in response.headers.get("Content-Type", "") else response.text
            return jsonify({
                "error": f"Inference service error ({response.status_code}): {error_data}"
            }), 502

        res_json = response.json()
        raw_content = res_json["choices"][0]["message"]["content"]
        parsed = clean_json_response(raw_content)
        normalized = validate_and_normalize(parsed, simple_metrics)

        # Merge deterministic rule-based NLP signals into category tags
        for cat_key, sigs in rule_signals.items():
            if cat_key in normalized["categories"] and sigs:
                current_tags = normalized["categories"][cat_key].get("legal_tags", [])
                for s in sigs:
                    if s not in current_tags:
                        current_tags.append(s)
                normalized["categories"][cat_key]["legal_tags"] = current_tags[:4]

        # Store in deterministic cache
        ANALYSIS_CACHE[cache_key] = normalized

        return jsonify(normalized)

    except requests.exceptions.Timeout:
        return jsonify({"error": "The contract analysis timed out. Please try again with a shorter section of text."}), 504
    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Network error contacting inference endpoint: {str(e)}"}), 502
    except Exception as e:
        return jsonify({"error": f"Failed to complete contract analysis: {str(e)}"}), 500


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
