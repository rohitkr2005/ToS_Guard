# ToS Guard: AI-Powered Legal Contract Risk Scanner

> An automated contract intelligence platform and consumer rights advisor that converts complex, verbose Terms of Service and Privacy Policies into visual, actionable risk assessments.

Live Demo: [https://tos-guard.onrender.com](https://tos-guard.onrender.com)  
Repository: [https://github.com/rohitkr2005/ToS_Guard](https://github.com/rohitkr2005/ToS_Guard)

---

## Overview

Over 90% of consumers click "I Agree" to Terms of Service agreements without reading them. Companies frequently bury restrictive clauses deep inside thousands of words of dense legal jargon: ranging from forced binding arbitration and class-action waivers to perpetual intellectual property transfers and behavioral tracking.

**ToS Guard** bridges this gap. It accepts either raw contract text or any public website link, extracts and normalizes the legal text, passes it through a hybrid NLP and LLM reasoning pipeline, and translates hidden legal risks into:
- A definitive consumer recommendation (**Safe to Agree**, **Proceed With Caution**, or **Do Not Agree**).
- A multi-axis **Risk Radar Chart** for intuitive visual evaluation.
- Plain-English, single-sentence category summaries paired with verbatim clause excerpts.
- Lexical readability metrics (reading ease, estimated reading time, and word volume).

---

## Key Features

### 1. Two Input Modes
- **Direct Text Scanning**: Paste raw agreement sections or entire policies for immediate analysis.
- **Live URL Scraping**: Input any web link (e.g. `https://example.com/terms`). The built-in DOM parser cleans boilerplate headers, navigation, footers, and scripts to isolate substantive legal text.

### 2. Multi-Dimensional Risk Taxonomy
The analysis evaluates 5 critical consumer vulnerability categories:
- **Data Selling**: Personal data collection, behavioral profiling, and commercialization with third-party data brokers or advertisers.
- **Auto-Renewal**: Hidden recurring subscriptions, lack of renewal notice, and strict no-refund clauses.
- **Arbitration**: Forced binding arbitration, surrender of jury trial rights, and class action lawsuit waivers.
- **Content Ownership**: Unilateral, royalty-free, perpetual, or sublicensable licenses claimed over user-generated content.
- **Account Deletion**: Artificial friction in deleting accounts, indefinite retention of personal data, and arbitrary termination clauses.

### 3. Actionable Consumer Verdict
Categorizes total contract risk with a clear traffic-light indicator and specific next-step guidance for non-lawyers:
- **0 to 39 (Low Risk)**: Recommended: Safe to Agree
- **40 to 69 (Moderate Risk)**: Proceed With Caution
- **70 to 100 (High Risk)**: Recommended: Do Not Agree

### 4. Hybrid NLP & Intelligence Engine
- **Deterministic Pattern Matching**: Pre-scans text using regular expressions targeting statutory terms of art (e.g. class action waivers, irrevocable licenses, binding arbitration).
- **Semantic LLM Classification**: Evaluates ambiguous, contextual contract nuances via high-parameter open models on OpenRouter (`nvidia/nemotron-3-super-120b-a12b:free`) with automatic fallback routing.
- **Extractive + Abstractive Summarization**: Pulls exact verbatim excerpts from the contract alongside one-sentence plain-English explanations.
- **Deterministic SHA-256 Caching**: Sub-second instant cache hits for duplicate scans of the same policy.

### 5. Production Ready & Modern UX
- **Chart.js Radar Chart**: Visual 5-point polygon displaying risk severity across all categories.
- **Three-State Theme Engine**: Clean obsidian dark mode, crisp light mode, and system preference detection via SVG toggles.
- **Automated Keep-Alive Daemon**: Background heartbeat ping thread keeps free cloud containers (such as Render) warm without manual intervention.

---

## System Architecture

```
User Input (Text or URL)
         │
         ▼
[ BeautifulSoup4 Web Ingestion ] ──> Strips scripts, styles & boilerplate
         │
         ▼
[ Text Normalization & Token Budgeting ] (Caps to 12,000 characters)
         │
         ├───> [ Deterministic Legal Regex Signal Scanner ]
         │         (Arbitration, Auto-Renewal, Data Rights signals)
         │
         ├───> [ Lexical & Readability Metric Calculator ]
         │         (Syllable density, read time, difficulty scale)
         │
         ▼
[ OpenRouter API Inference Cascade ]
         │  (Primary: nvidia/nemotron-3-super-120b-a12b:free)
         │  (Fallbacks: nemotron-3.5-super-vl, nemotron-3-ultra)
         │
         ▼
[ JSON Schema Validation & Cache Storing (SHA-256) ]
         │
         ▼
[ Consumer Verdict Engine & Radar Chart Rendering ]
```

---

## Tech Stack

- **Backend**: Python 3.10+, Flask, Gunicorn
- **Data Scraping & NLP**: BeautifulSoup4, Regular Expressions, Lexical Analysis
- **AI Inference**: OpenRouter API (`nvidia/nemotron-3-super-120b-a12b:free`)
- **Frontend**: HTML5, Vanilla JavaScript, Tailwind CSS (CDN), Chart.js
- **Deployment**: Render (Web Service container with Gunicorn)

---

## Local Development Setup

### Prerequisites
- Python 3.10 or higher
- Git
- An OpenRouter API Key (free tier available at [openrouter.ai](https://openrouter.ai))

### Installation

1. **Clone the repository**:
   ```bash
   git clone https://github.com/rohitkr2005/ToS_Guard.git
   cd ToS_Guard
   ```

2. **Create and activate a virtual environment**:
   - On Windows (PowerShell):
     ```powershell
     python -m venv venv
     .\venv\Scripts\Activate.ps1
     ```
   - On macOS/Linux:
     ```bash
     python3 -m venv venv
     source venv/bin/activate
     ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment variables**:
   Create a `.env` file in the root directory:
   ```env
   OPENROUTER_API_KEY=your_openrouter_api_key_here
   CUSTOM_DOMAIN=tosguard.com
   PORT=5000
   ```

5. **Start the development server**:
   ```bash
   python app.py
   ```
   Open your browser and navigate to `http://127.0.0.1:5000`.

---

## Production Deployment (Render)

This project is pre-configured for zero-friction deployment on Render:

1. Push your repository to GitHub.
2. In the [Render Dashboard](https://dashboard.render.com), create a **New Web Service** connected to your repo.
3. Configure the build parameters:
   - **Environment**: Python 3
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn app:app --workers 1 --threads 4 --timeout 120`
4. Under **Environment Variables**, add:
   - `OPENROUTER_API_KEY`: *(your OpenRouter API key)*
5. Click **Deploy Web Service**.

> The included keep-alive daemon will automatically detect `RENDER_EXTERNAL_URL` and ping `/health` every 8 minutes to prevent the free-tier container from idling.

---

## Project Structure

```
ToS_Guard/
├── app.py              # Main Flask app, NLP logic, caching & inference routes
├── requirements.txt    # Production Python dependencies
├── Procfile            # Gunicorn process manager configuration for Render
├── .gitignore          # Excludes .env, virtual environments, and cache files
├── README.md           # Project documentation
├── static/
│   └── favicon.svg     # SVG shield icon
└── templates/
    ├── index.html      # Main contract analysis dashboard & radar chart
    ├── privacy.html    # Privacy policy page
    └── terms.html      # Terms of service page
```

---

## Disclaimer

ToS Guard is an automated artificial intelligence tool designed for informational and educational purposes only. It does not provide formal legal advice, nor does it establish an attorney-client relationship. Users should consult qualified legal counsel for binding contract disputes.

---

## License

This project is licensed under the MIT License. Feel free to use, modify, and distribute this software according to the license terms.
