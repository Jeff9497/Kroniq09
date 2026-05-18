"""
kroniqo-agent: Chronicle Agent
Backends: Claude | Gemini | Groq | Cerebras | GLM5 | Mistral
Supports structured commands AND free natural chat mode.
"""

import sys
import os
import requests
from pathlib import Path

# Auto-load .env config if present
_env_file = Path(__file__).parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'kroniqo-core'))
from consequence_graph import log_decision, record_outcome, get_biography, get_behavioral_modifier

# Auto-judge (optional — works if API keys are set)
try:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'tools'))
    from auto_judge import auto_judge
    AUTO_JUDGE_AVAILABLE = True
except ImportError:
    AUTO_JUDGE_AVAILABLE = False

# ── Backend configs ───────────────────────────────────────────────────────────
BACKENDS = {
    "claude": {
        "url":    "https://api.anthropic.com/v1/messages",
        "model":  "claude-sonnet-4-20250514",
        "key_env": "ANTHROPIC_API_KEY",
        "style":  "anthropic",
    },
    "gemini": {
        "url":    "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "model":  "gemini-2.0-flash",
        "key_env": "GEMINI_API_KEY",
        "style":  "openai",
        "note":   "1,500 req/day free",
    },
    "groq": {
        "url":    "https://api.groq.com/openai/v1/chat/completions",
        "model":  "llama-3.3-70b-versatile",
        "key_env": "GROQ_API_KEY",
        "style":  "openai",
        "note":   "14,400 req/day free — fastest",
    },
    "cerebras": {
        "url":    "https://api.cerebras.ai/v1/chat/completions",
        "model":  "llama3.3-70b",
        "key_env": "CEREBRAS_API_KEY",
        "style":  "openai",
        "note":   "1M tokens/day free",
    },
    "glm5": {
        "url":    "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        "model":  "glm-4",
        "key_env": "GLM_API_KEY",
        "style":  "openai",
        "note":   "Small free tier",
    },
    "mistral": {
        "url":    "https://api.mistral.ai/v1/chat/completions",
        "model":  "mistral-small-latest",
        "key_env": "MISTRAL_API_KEY",
        "style":  "openai",
        "note":   "1B tokens/month free",
    },
}

FALLBACK_CHAIN = ["gemini", "groq", "cerebras", "claude"]
DEFAULT_BACKEND = "groq"

# Domain keywords for auto-detection in free chat mode
DOMAIN_HINTS = {
    "geography":  ["capital", "country", "continent", "city", "ocean", "river", "located", "where is"],
    "math":       ["calculate", "solve", "prime", "equation", "number", "sum", "multiply", "divide", "percent", "factorial"],
    "trivia":     ["who invented", "what year", "which country won", "how many bones", "first person", "first african"],
    "science":    ["quantum", "physics", "chemistry", "biology", "atom", "energy", "gravity", "machine learning", "half-life", "planet"],
    "logic":      ["riddle", "puzzle", "lateral thinking", "logic puzzle", "rooster", "coins total",
                   "doctor says", "therefore", "deduce", "must be true", "which side does",
                   "if all", "trick question", "impossible", "two coins", "three jugs"],
    "code_debug": ["bug", "error", "fix", "debug", "code", "function", "syntax", "crash", "exception"],
}


# ── Domain auto-detection ─────────────────────────────────────────────────────
def detect_domain(text: str) -> str:
    text_lower = text.lower()
    scores = {domain: 0 for domain in DOMAIN_HINTS}
    for domain, keywords in DOMAIN_HINTS.items():
        for kw in keywords:
            if kw in text_lower:
                scores[domain] += 1
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "general"


# ── System prompt ─────────────────────────────────────────────────────────────
def build_system_prompt(domain: str) -> str:
    modifier = get_behavioral_modifier(domain)
    bio      = get_biography()

    age_desc = (
        "You are newly initialized. You have no prior experience."
        if modifier["age"] == 0 else
        f"You have made {modifier['age']} consequential decisions in your lifetime."
    )

    risk_instruction = {
        "conservative": "Your recent performance in this domain has been poor. Be cautious, hedge your answers, flag uncertainty explicitly.",
        "bold":         "Your recent performance has been strong. You may be more decisive and confident.",
        "neutral":      "Proceed with balanced confidence.",
    }.get(modifier["risk_posture"], "Proceed with balanced confidence.")

    bio_note = modifier["biography_note"]
    confidence_note = (
        f"In [{domain}] your weighted accuracy is {bio_note.get('weighted_accuracy','?')} "
        f"and you are currently {bio_note.get('calibration','uncalibrated')}."
        if isinstance(bio_note, dict) else bio_note
    )

    return f"""You are Kroniqo, an AI agent that ages through experience.

{age_desc}

Biography:
{bio['summary']}

Domain: [{domain}]
{confidence_note}

Behavioral instruction: {risk_instruction}

Rules:
- Answer clearly and helpfully.
- End your response with exactly one line: CONFIDENCE: X.X  (0.0 to 1.0)
- Let your track record genuinely shape how certain you sound."""


# ── LLM call ─────────────────────────────────────────────────────────────────
def call_llm(system: str, user: str, backend: str) -> str:
    cfg = BACKENDS[backend]
    key = os.environ.get(cfg["key_env"], "").strip()
    if not key:
        raise ValueError(f"No API key — set {cfg['key_env']}")

    if cfg["style"] == "anthropic":
        headers = {
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": cfg["model"],
            "max_tokens": 1024,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        r = requests.post(cfg["url"], headers=headers, json=payload, timeout=30)
        r.raise_for_status()
        return r.json()["content"][0]["text"]

    else:
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": cfg["model"],
            "max_tokens": 1024,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
        }
        r = requests.post(cfg["url"], headers=headers, json=payload, timeout=30)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]


def call_with_fallback(system: str, user: str, primary: str) -> tuple:
    chain = [primary] + [b for b in FALLBACK_CHAIN if b != primary]
    errors = []
    for backend in chain:
        key = os.environ.get(BACKENDS[backend]["key_env"], "").strip()
        if not key:
            errors.append(f"{backend}: no key set")
            continue
        try:
            result = call_llm(system, user, backend)
            if backend != primary:
                print(f"  [Fallback used: {backend.upper()}]")
            return result, backend
        except Exception as e:
            errors.append(f"{backend}: {e}")
            print(f"  [!] {backend.upper()} failed — trying next...")

    # All failed — show helpful message
    print("\n  No backend responded. Checked:")
    for e in errors:
        print(f"    {e}")
    print("\n  Fix: export the key in your terminal, e.g.:")
    print("    export GROQ_API_KEY=your_key_here")
    print("  Get a free key at: console.groq.com\n")
    raise RuntimeError("All backends failed.")


# ── Parse confidence ──────────────────────────────────────────────────────────
def parse_confidence(text: str) -> float:
    for line in reversed(text.strip().split("\n")):
        if "CONFIDENCE:" in line.upper():
            try:
                return min(1.0, max(0.0, float(line.split(":")[-1].strip())))
            except ValueError:
                pass
    return 0.5


# ── Core ask function ─────────────────────────────────────────────────────────
def ask(domain: str, task: str, backend: str = DEFAULT_BACKEND):
    system = build_system_prompt(domain)
    answer, used_backend = call_with_fallback(system, task, backend)
    confidence  = parse_confidence(answer)
    decision_id = log_decision(domain, task, confidence)

    print(f"\n{'='*60}")
    print(f"Kroniqo [{used_backend.upper()}] — Domain: {domain}")
    print(f"{'='*60}")
    print(answer)
    print(f"\nDecision ID : {decision_id}  |  Confidence: {confidence}")

    # Auto-judge if available
    if AUTO_JUDGE_AVAILABLE:
        print(f"  [AutoJudge running...]")
        verdict = auto_judge(decision_id, domain, task, answer)
        if verdict in ("correct", "wrong"):
            print(f"  [AutoJudge] Done — no manual outcome needed.")
        elif verdict == "pending":
            print(f"  To record manually: outcome {decision_id} correct/wrong")
    else:
        print(f"  To record outcome: outcome {decision_id} correct/wrong")

    print(f"{'='*60}\n")
    return answer, confidence, decision_id


# ── Biography display ─────────────────────────────────────────────────────────
def show_biography():
    bio = get_biography()
    print(f"\n{'='*60}")
    print("KRONIQO BIOGRAPHY")
    print(f"{'='*60}")
    print(f"Experiential Age : {bio['age']} decisions")
    print(f"Summary          : {bio['summary']}")
    if bio["domains"]:
        print("\nDomain Breakdown:")
        for domain, s in bio["domains"].items():
            print(f"\n  [{domain}]")
            print(f"    Decisions         : {s['total_decisions']}")
            print(f"    Weighted accuracy : {s['weighted_accuracy']:.0%}")
            print(f"    Calibration       : {s['calibration']}")
            print(f"    Recent form       : {s['recent_form']}")
    print(f"{'='*60}\n")


def show_backends(active: str):
    print(f"\n{'='*60}")
    print("BACKENDS")
    print(f"{'='*60}")
    for name, cfg in BACKENDS.items():
        key_set = "✓" if os.environ.get(cfg["key_env"], "").strip() else "✗ no key"
        note    = cfg.get("note", "")
        marker  = " ← active" if name == active else ""
        print(f"  {name:<12} {key_set:<14} {note}{marker}")
    print(f"\nFallback chain: {' → '.join(FALLBACK_CHAIN)}")
    print(f"\nTo set a key (Linux/Termux):  export GROQ_API_KEY=your_key")
    print(f"To set a key (Windows):       set GROQ_API_KEY=your_key")
    print(f"{'='*60}\n")


# ── Setup intent handler ─────────────────────────────────────────────────────
import re as _re
from pathlib import Path as _Path

_ENV_FILE = _Path(__file__).parent / ".env"

def _load_env_file():
    config = {}
    if _ENV_FILE.exists():
        for line in _ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                config[k.strip()] = v.strip()
    return config

def _save_env_file(config: dict):
    lines = ["# Kroniqo config", ""]
    for k, v in config.items():
        lines.append(f"{k}={v}")
    _ENV_FILE.write_text("\n".join(lines))

def _test_telegram_token(token: str):
    try:
        r = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=8)
        if r.status_code == 200:
            return r.json().get("result")
    except:
        pass
    return None

def _get_chat_id(token: str):
    try:
        r = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=8)
        if r.status_code == 200:
            updates = r.json().get("result", [])
            if updates:
                return str(updates[-1]["message"]["chat"]["id"])
    except:
        pass
    return None

def _send_telegram(token: str, chat_id: str, text: str) -> bool:
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=8
        )
        return r.status_code == 200
    except:
        return False

def handle_setup_intent(text: str) -> bool:
    """
    Detect setup intents in natural language and handle them.
    Returns True if this was a setup command, False if normal chat.
    """
    lower = text.lower()

    # ── Detect API key mentions ───────────────────────────────────────────────
    groq_match = _re.search(r'gsk_[A-Za-z0-9]{40,}', text)
    gemini_match = _re.search(r'AIza[A-Za-z0-9_-]{35,}', text)
    cerebras_match = _re.search(r'csk-[A-Za-z0-9]{40,}', text)

    # ── Detect Telegram bot token ─────────────────────────────────────────────
    tg_token_match = _re.search(r'\d{8,12}:[A-Za-z0-9_-]{35,}', text)

    # ── Detect chat_id (standalone number, often negative for groups) ─────────
    chatid_match = _re.search(r'(?:chat.?id|my.?id)[^\d-]*(-?\d{6,})', lower + " " + text, _re.IGNORECASE)
    if not chatid_match:
        chatid_match = _re.search(r'(-?\d{9,})', text)  # bare large number

    config = _load_env_file()

    handled = False

    # Handle Groq key
    if groq_match:
        key = groq_match.group(0)
        print(f"\n  Detected Groq API key. Testing...", end=" ", flush=True)
        try:
            r = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={"model": "llama-3.3-70b-versatile", "max_tokens": 5,
                      "messages": [{"role": "user", "content": "hi"}]},
                timeout=10
            )
            if r.status_code == 200:
                print("✓ Valid")
                config["GROQ_API_KEY"] = key
                os.environ["GROQ_API_KEY"] = key
                _save_env_file(config)
                print("  Groq key saved. You can now use the groq backend.")
            else:
                print(f"✗ Rejected (status {r.status_code})")
        except Exception as e:
            print(f"✗ Could not reach Groq: {e}")
        handled = True

    # Handle Gemini key
    if gemini_match:
        key = gemini_match.group(0)
        print(f"\n  Detected Gemini API key. Testing...", end=" ", flush=True)
        try:
            r = requests.post(
                "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={"model": "gemini-2.0-flash", "max_tokens": 5,
                      "messages": [{"role": "user", "content": "hi"}]},
                timeout=10
            )
            if r.status_code == 200:
                print("✓ Valid")
                config["GEMINI_API_KEY"] = key
                os.environ["GEMINI_API_KEY"] = key
                _save_env_file(config)
                print("  Gemini key saved.")
            else:
                print(f"✗ Rejected (status {r.status_code})")
        except Exception as e:
            print(f"✗ Could not reach Gemini: {e}")
        handled = True

    # Handle Telegram bot token
    if tg_token_match:
        token = tg_token_match.group(0)
        print(f"\n  Detected Telegram bot token. Verifying...", end=" ", flush=True)
        bot_info = _test_telegram_token(token)
        if bot_info:
            print(f"✓ Bot: @{bot_info.get('username')}")
            config["TELEGRAM_BOT_TOKEN"] = token
            os.environ["TELEGRAM_BOT_TOKEN"] = token
            _save_env_file(config)
            print(f"  Token saved.")

            # Try to get chat_id automatically
            chat_id = config.get("TELEGRAM_CHAT_ID", "")
            if not chat_id:
                print(f"\n  To connect your Telegram account:")
                print(f"  1. Open Telegram → message @{bot_info.get('username')}")
                print(f"  2. Send any message (e.g. hello)")
                input(f"  3. Press Enter when done...")
                chat_id = _get_chat_id(token)
                if chat_id:
                    print(f"  ✓ Chat ID detected: {chat_id}")
                    config["TELEGRAM_CHAT_ID"] = chat_id
                    os.environ["TELEGRAM_CHAT_ID"] = chat_id
                    _save_env_file(config)
                    # Send confirmation
                    print(f"  Sending you a message on Telegram...", end=" ", flush=True)
                    ok = _send_telegram(token, chat_id,
                        "Kroniqo is connected.\n\nCommands:\n/ask <domain> <question>\n/biography\n/debug <code>\n/outcome <id> correct/wrong\n\nOr just message me naturally.")
                    print("✓ Sent" if ok else "✗ Failed — check chat ID")
                else:
                    print(f"  Could not auto-detect chat ID.")
                    print(f"  Paste your chat ID: (get it from @userinfobot on Telegram)")
        else:
            print("✗ Invalid token")
        handled = True

    # Handle bare chat_id with existing token
    if chatid_match and not tg_token_match:
        token = config.get("TELEGRAM_BOT_TOKEN", "")
        if token:
            chat_id = chatid_match.group(1) if chatid_match.lastindex else chatid_match.group(0)
            print(f"\n  Detected chat ID: {chat_id}")
            config["TELEGRAM_CHAT_ID"] = chat_id
            os.environ["TELEGRAM_CHAT_ID"] = chat_id
            _save_env_file(config)
            print(f"  Saved. Testing connection...", end=" ", flush=True)
            ok = _send_telegram(token, chat_id, "Kroniqo connected. Ready.")
            print("✓ Message sent" if ok else "✗ Could not send — verify the ID")
            handled = True

    # Handle "setup telegram" / "how do I use telegram" intent
    if not handled and any(w in lower for w in ["setup telegram", "configure telegram", "telegram bot", "use telegram", "start telegram"]):
        token = config.get("TELEGRAM_BOT_TOKEN", "")
        if token:
            print(f"\n  Telegram already configured. Run:")
            print(f"  python kroniqo-agent/telegram_bot.py")
        else:
            print(f"""
  To connect Kroniqo to Telegram:

  1. Open Telegram → message @BotFather → /newbot
  2. Follow prompts, copy the bot token
  3. Paste it here: "configure <your_token>"

  That's it. I'll handle the rest automatically.
""")
        handled = True

    # Handle "show config" / "what keys do I have"
    if not handled and any(w in lower for w in ["show config", "my keys", "what keys", "configured", "setup status"]):
        config = _load_env_file()
        print("\n  Current configuration:")
        keys_to_show = ["GROQ_API_KEY", "GEMINI_API_KEY", "CEREBRAS_API_KEY",
                        "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "ANTHROPIC_API_KEY"]
        for k in keys_to_show:
            v = config.get(k, os.environ.get(k, ""))
            if v:
                masked = v[:8] + "..." + v[-4:] if len(v) > 12 else "***"
                print(f"  ✓ {k}: {masked}")
            else:
                print(f"  ✗ {k}: not set")
        print()
        handled = True

    return handled


# ── CLI ───────────────────────────────────────────────────────────────────────
COMMANDS = {"ask", "outcome", "biography", "backends", "switch", "quit", "exit", "q", "help"}

HELP = """
Commands:
  ask        — structured ask with domain selection
  outcome    — record the result of a past decision
  biography  — show Kroniqo's full biography
  backends   — show all backends and API key status
  switch     — change active backend
  quit       — exit

Or just TYPE ANYTHING and Kroniqo will answer directly.
Domain is auto-detected from your message.
After each answer, record outcome with: outcome <id> correct/wrong
"""

if __name__ == "__main__":
    backend = DEFAULT_BACKEND
    last_decision_id = None

    print("╔══════════════════════════════╗")
    print("║   Kroniqo Agent — CLI        ║")
    print("╚══════════════════════════════╝")
    print(f"Active backend : {backend.upper()}")
    print("Just type to chat, or use commands. Type 'help' for full list.\n")

    while True:
        try:
            user_input = input("kroniqo> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            break

        if not user_input:
            continue

        first_word = user_input.split()[0].lower()

        # ── Structured commands ───────────────────────────────────────────────
        if first_word == "ask":
            domain = input("  Domain (geography/math/trivia/science/logic/code_debug): ").strip() or "general"
            task   = input("  Task  : ").strip()
            if task:
                _, _, last_decision_id = ask(domain, task, backend)

        elif first_word == "outcome":
            # Support inline: "outcome 3 correct" or interactive
            parts = user_input.split()
            if len(parts) >= 3:
                try:
                    did     = int(parts[1])
                    outcome = parts[2].lower().split("/")[0]  # handle "correct/wrong" → "correct"
                    mag     = parts[3] if len(parts) > 3 else "medium"
                    if outcome not in ("correct", "wrong", "partial"):
                        print(f"  Invalid outcome '{outcome}'. Use: correct, wrong, or partial")
                    else:
                        record_outcome(did, outcome, mag)
                        print(f"  Recorded decision {did} as {outcome}. Kroniqo has aged.\n")
                except (ValueError, IndexError):
                    print("  Usage: outcome <id> <correct/wrong> [small/medium/large]")
            else:
                try:
                    did     = int(input("  Decision ID : ").strip())
                    outcome = input("  Outcome (correct/wrong/partial): ").strip()
                    mag     = input("  Magnitude (small/medium/large) [medium]: ").strip() or "medium"
                    notes   = input("  Notes (optional): ").strip()
                    record_outcome(did, outcome, mag, notes)
                    print(f"  Recorded. Kroniqo has aged.\n")
                except ValueError:
                    print("  Invalid ID.")

        elif first_word == "biography":
            show_biography()

        elif first_word == "backends":
            show_backends(backend)

        elif first_word == "switch":
            show_backends(backend)
            choice = input("  Choose backend: ").strip().lower()
            if choice in BACKENDS:
                backend = choice
                print(f"  Switched to {backend.upper()}\n")
            else:
                print(f"  Unknown. Options: {list(BACKENDS.keys())}")

        elif first_word in ("quit", "exit", "q"):
            print("Goodbye.")
            break

        elif first_word == "help":
            print(HELP)

        # ── Free chat mode — anything else ────────────────────────────────────
        else:
            # Check for setup intents first
            setup_result = handle_setup_intent(user_input)
            if setup_result:
                pass  # setup handled it
            else:
                domain = detect_domain(user_input)
                print(f"  [auto-domain: {domain}]")
                try:
                    _, _, last_decision_id = ask(domain, user_input, backend)
                    if not AUTO_JUDGE_AVAILABLE:
                        print(f"  To record outcome: outcome {last_decision_id} correct/wrong\n")
                except RuntimeError:
                    pass  # error already printed inside ask
