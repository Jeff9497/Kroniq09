"""
kroniqo-agent/agent.py
Kroniqo — AI that ages through experience.
One file: CLI + Telegram bot run together automatically.
"""

import sys
import os
import requests
import threading
from pathlib import Path
import re as _re

# Auto-load .env
_env_file = Path(__file__).parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'kroniqo-core'))
from consequence_graph import log_decision, record_outcome, get_biography, get_behavioral_modifier

try:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'tools'))
    from auto_judge import auto_judge
    AUTO_JUDGE_AVAILABLE = True
except ImportError:
    AUTO_JUDGE_AVAILABLE = False

BACKENDS = {
    "claude":   {"url": "https://api.anthropic.com/v1/messages", "model": "claude-sonnet-4-20250514", "key_env": "ANTHROPIC_API_KEY", "style": "anthropic"},
    "gemini":   {"url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions", "model": "gemini-2.0-flash", "key_env": "GEMINI_API_KEY", "style": "openai", "note": "1,500 req/day free"},
    "groq":     {"url": "https://api.groq.com/openai/v1/chat/completions", "model": "llama-3.3-70b-versatile", "key_env": "GROQ_API_KEY", "style": "openai", "note": "1,000 req/day free — fastest"},
    "cerebras": {"url": "https://api.cerebras.ai/v1/chat/completions", "model": "llama3.3-70b", "key_env": "CEREBRAS_API_KEY", "style": "openai", "note": "1M tokens/day free"},
    "glm5":     {"url": "https://open.bigmodel.cn/api/paas/v4/chat/completions", "model": "glm-4", "key_env": "GLM_API_KEY", "style": "openai", "note": "Small free tier"},
    "mistral":  {"url": "https://api.mistral.ai/v1/chat/completions", "model": "mistral-small-latest", "key_env": "MISTRAL_API_KEY", "style": "openai", "note": "1B tokens/month free"},
}
FALLBACK_CHAIN = ["gemini", "groq", "cerebras", "claude"]
DEFAULT_BACKEND = "groq"

DOMAIN_HINTS = {
    "geography":  ["capital", "country", "continent", "city", "ocean", "river", "located", "where is"],
    "math":       ["calculate", "solve", "prime", "equation", "number", "sum", "multiply", "divide", "percent", "factorial"],
    "trivia":     ["who invented", "what year", "which country won", "how many bones", "first person", "first african"],
    "science":    ["quantum", "physics", "chemistry", "biology", "atom", "energy", "gravity", "machine learning", "half-life", "planet"],
    "logic":      ["riddle", "puzzle", "lateral thinking", "logic puzzle", "rooster", "coins total", "doctor says", "therefore", "deduce", "must be true", "which side does", "if all", "trick question", "impossible", "two coins", "three jugs"],
    "code_debug": ["bug", "error", "fix", "debug", "code", "function", "syntax", "crash", "exception"],
}

def detect_domain(text):
    tl = text.lower()
    scores = {d: sum(1 for kw in kws if kw in tl) for d, kws in DOMAIN_HINTS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "general"

def build_system_prompt(domain):
    modifier = get_behavioral_modifier(domain)
    bio = get_biography()
    age_desc = "You are newly initialized. You have no prior experience." if modifier["age"] == 0 else f"You have made {modifier['age']} consequential decisions."
    risk = {"conservative": "Recent performance poor. Be cautious, hedge, flag uncertainty.", "bold": "Recent performance strong. Be decisive.", "neutral": "Proceed with balanced confidence."}.get(modifier["risk_posture"], "Proceed with balanced confidence.")
    bio_note = modifier["biography_note"]
    cnote = (f"In [{domain}] weighted accuracy is {bio_note.get('weighted_accuracy','?')}, calibration: {bio_note.get('calibration','unknown')}." if isinstance(bio_note, dict) else bio_note)
    return f"""You are Kroniqo, an AI agent that ages through experience.\n\n{age_desc}\n\nBiography:\n{bio['summary']}\n\nDomain: [{domain}]\n{cnote}\n\nInstruction: {risk}\n\nRules:\n- Answer clearly.\n- End with exactly: CONFIDENCE: X.X (0.0–1.0)\n- Let your track record shape your tone."""

def call_llm(system, user, backend):
    cfg = BACKENDS[backend]
    key = os.environ.get(cfg["key_env"], "").strip()
    if not key:
        raise ValueError(f"No key for {backend} — set {cfg['key_env']}")
    if cfg["style"] == "anthropic":
        r = requests.post(cfg["url"], headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": cfg["model"], "max_tokens": 1024, "system": system, "messages": [{"role": "user", "content": user}]}, timeout=30)
        r.raise_for_status()
        return r.json()["content"][0]["text"]
    else:
        r = requests.post(cfg["url"], headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": cfg["model"], "max_tokens": 1024, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}, timeout=30)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]

def call_with_fallback(system, user, primary):
    chain = [primary] + [b for b in FALLBACK_CHAIN if b != primary]
    errors = []
    for b in chain:
        key = os.environ.get(BACKENDS[b]["key_env"], "").strip()
        if not key:
            errors.append(f"{b}: no key"); continue
        try:
            result = call_llm(system, user, b)
            if b != primary: print(f"  [Fallback: {b.upper()}]")
            return result, b
        except Exception as e:
            errors.append(f"{b}: {e}"); print(f"  [!] {b.upper()} failed")
    print("\n  All backends failed:", errors)
    print("  Paste your GROQ_API_KEY here or: export GROQ_API_KEY=key (console.groq.com)\n")
    raise RuntimeError("All backends failed.")

def parse_confidence(text):
    for line in reversed(text.strip().split("\n")):
        if "CONFIDENCE:" in line.upper():
            try: return min(1.0, max(0.0, float(line.split(":")[-1].strip())))
            except: pass
    return 0.5

def ask(domain, task, backend=DEFAULT_BACKEND):
    system = build_system_prompt(domain)
    answer, used = call_with_fallback(system, task, backend)
    confidence = parse_confidence(answer)
    decision_id = log_decision(domain, task, confidence)
    print(f"\n{'='*60}")
    print(f"Kroniqo [{used.upper()}] — Domain: {domain}")
    print(f"{'='*60}")
    print(answer)
    print(f"\nDecision ID : {decision_id}  |  Confidence: {confidence}")
    # Skip autojudge for general/conversational — no factual outcome to verify
    if AUTO_JUDGE_AVAILABLE and domain != "general":
        print("  [AutoJudge running...]")
        verdict = auto_judge(decision_id, domain, task, answer)
        if verdict in ("correct", "wrong"):
            print("  [AutoJudge] Recorded automatically.")
        else:
            print(f"  To record manually: outcome {decision_id} correct/wrong")
    elif domain == "general":
        print(f"  [Conversational — no outcome needed]")
    else:
        print(f"  To record outcome: outcome {decision_id} correct/wrong")
    print(f"{'='*60}\n")
    return answer, confidence, decision_id

def show_biography():
    bio = get_biography()
    print(f"\n{'='*60}\nKRONIQO BIOGRAPHY\n{'='*60}")
    print(f"Experiential Age : {bio['age']} decisions")
    print(f"Summary          : {bio['summary']}")
    if bio["domains"]:
        print("\nDomain Breakdown:")
        for d, s in bio["domains"].items():
            print(f"\n  [{d}]\n    Decisions: {s['total_decisions']} | Accuracy: {s['weighted_accuracy']:.0%} | {s['calibration']} | Recent: {s['recent_form']}")
    print(f"{'='*60}\n")

def show_backends(active):
    print(f"\n{'='*60}\nBACKENDS\n{'='*60}")
    for name, cfg in BACKENDS.items():
        ks = "✓" if os.environ.get(cfg["key_env"], "").strip() else "✗"
        print(f"  {name:<12} {ks}  {cfg.get('note','')}{'  ← active' if name==active else ''}")
    print(f"\nFallback: {' → '.join(FALLBACK_CHAIN)}")
    print("Paste any API key here to configure it automatically.\n")

# ── Setup helpers ─────────────────────────────────────────────────────────────
_ENV_FILE = Path(__file__).parent / ".env"

def _load_env():
    cfg = {}
    if _ENV_FILE.exists():
        for line in _ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1); cfg[k.strip()] = v.strip()
    return cfg

def _save_env(cfg):
    _ENV_FILE.write_text("# Kroniqo config\n\n" + "\n".join(f"{k}={v}" for k, v in cfg.items()))

def _test_tg(token):
    try:
        r = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=8)
        return r.json().get("result") if r.status_code == 200 else None
    except: return None

def _get_chat_id(token):
    try:
        r = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=8)
        updates = r.json().get("result", []) if r.status_code == 200 else []
        return str(updates[-1]["message"]["chat"]["id"]) if updates else None
    except: return None

def _send_tg(token, chat_id, text):
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id": chat_id, "text": text}, timeout=8)
        return r.status_code == 200
    except: return False

def handle_setup_intent(text):
    lower = text.lower()
    groq_m   = _re.search(r'gsk_[A-Za-z0-9]{40,}', text)
    gemini_m = _re.search(r'AIza[A-Za-z0-9_-]{35,}', text)
    cbrS_m   = _re.search(r'csk-[A-Za-z0-9]{40,}', text)
    tg_m     = _re.search(r'\d{8,12}:[A-Za-z0-9_-]{35,}', text)
    cid_m    = _re.search(r'(?:chat.?id|my.?id)[^\d-]*(-?\d{6,})', lower + " " + text, _re.IGNORECASE)
    if not cid_m and not tg_m:
        cid_m = _re.search(r'(?<!\d)(-?\d{9,})(?!\d)', text)

    cfg = _load_env()
    handled = False

    if groq_m:
        key = groq_m.group(0)
        print("\n  Detected Groq key. Testing...", end=" ", flush=True)
        try:
            r = requests.post("https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={"model": "llama-3.3-70b-versatile", "max_tokens": 5, "messages": [{"role": "user", "content": "hi"}]}, timeout=10)
            if r.status_code == 200:
                print("✓"); cfg["GROQ_API_KEY"] = key; os.environ["GROQ_API_KEY"] = key; _save_env(cfg)
                print("  Saved and active.\n")
            else: print(f"✗ status {r.status_code}\n")
        except Exception as e: print(f"✗ {e}\n")
        handled = True

    if gemini_m:
        key = gemini_m.group(0)
        print("\n  Detected Gemini key. Testing...", end=" ", flush=True)
        try:
            r = requests.post("https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={"model": "gemini-2.0-flash", "max_tokens": 5, "messages": [{"role": "user", "content": "hi"}]}, timeout=10)
            if r.status_code == 200:
                print("✓"); cfg["GEMINI_API_KEY"] = key; os.environ["GEMINI_API_KEY"] = key; _save_env(cfg)
                print("  Saved.\n")
            else: print(f"✗\n")
        except Exception as e: print(f"✗ {e}\n")
        handled = True

    if cbrS_m:
        key = cbrS_m.group(0)
        cfg["CEREBRAS_API_KEY"] = key; os.environ["CEREBRAS_API_KEY"] = key; _save_env(cfg)
        print("\n  Cerebras key saved.\n"); handled = True

    if tg_m:
        token = tg_m.group(0)
        print("\n  Detected Telegram token. Verifying...", end=" ", flush=True)
        bot_info = _test_tg(token)
        if bot_info:
            uname = bot_info.get('username')
            print(f"✓ @{uname}")
            cfg["TELEGRAM_BOT_TOKEN"] = token; os.environ["TELEGRAM_BOT_TOKEN"] = token; _save_env(cfg)
            chat_id = cfg.get("TELEGRAM_CHAT_ID", "")
            if not chat_id:
                print(f"\n  Link your account:")
                print(f"  1. Message @{uname} on Telegram")
                print(f"  2. Send any message")
                input(f"  3. Press Enter...")
                chat_id = _get_chat_id(token)
                if chat_id:
                    print(f"  ✓ Chat ID: {chat_id}")
                    cfg["TELEGRAM_CHAT_ID"] = chat_id; os.environ["TELEGRAM_CHAT_ID"] = chat_id; _save_env(cfg)
                    ok = _send_tg(token, chat_id, "Kroniqo connected.\n\nJust message me naturally, or:\n/ask <domain> <question>\n/biography\n/debug <code>\n/outcome <id> correct/wrong")
                    print("  Confirmation sent.\n" if ok else "  Could not send — check chat ID.\n")
                    _start_telegram_thread()
                else:
                    print("  Could not auto-detect. Paste your chat ID here.\n")
        else:
            print("✗ Invalid\n")
        handled = True

    if cid_m and not tg_m:
        token = cfg.get("TELEGRAM_BOT_TOKEN", os.environ.get("TELEGRAM_BOT_TOKEN", ""))
        if token:
            chat_id = cid_m.group(1) if cid_m.lastindex else cid_m.group(0)
            print(f"\n  Chat ID: {chat_id}. Saving...", end=" ", flush=True)
            cfg["TELEGRAM_CHAT_ID"] = chat_id; os.environ["TELEGRAM_CHAT_ID"] = chat_id; _save_env(cfg)
            ok = _send_tg(token, chat_id, "Kroniqo connected. Ready.")
            print("✓ Sent\n" if ok else "✗ Failed\n")
            handled = True

    if not handled and any(w in lower for w in ["setup telegram", "configure telegram", "use telegram", "start telegram", "telegram bot"]):
        token = cfg.get("TELEGRAM_BOT_TOKEN", "")
        if token:
            print("\n  Telegram is configured and running in the background.\n  Just open Telegram and message the bot.\n")
        else:
            print("\n  To setup Telegram:\n  1. Message @BotFather → /newbot\n  2. Copy the token\n  3. Paste it here — I'll handle the rest.\n")
        handled = True

    if not handled and any(w in lower for w in ["show config", "my keys", "what keys", "setup status"]):
        print("\n  Configuration:")
        for k in ["GROQ_API_KEY", "GEMINI_API_KEY", "CEREBRAS_API_KEY", "ANTHROPIC_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"]:
            v = cfg.get(k, os.environ.get(k, ""))
            print(f"  {'✓' if v else '✗'} {k}: {v[:8]+'...'+v[-4:] if v and len(v)>12 else ('set' if v else 'not set')}")
        print()
        handled = True

    return handled

# ── Telegram thread ───────────────────────────────────────────────────────────
_tg_thread = None

def _start_telegram_thread():
    global _tg_thread
    if not os.environ.get("TELEGRAM_BOT_TOKEN", "").strip(): return
    if _tg_thread and _tg_thread.is_alive(): return
    try:
        from telegram_bot import run_telegram
        _tg_thread = threading.Thread(target=run_telegram, daemon=True, name="TelegramBot")
        _tg_thread.start()
        print("  [Telegram] Bot running in background\n")
    except Exception as e:
        print(f"  [Telegram] Could not start: {e}\n")

# ── CLI ───────────────────────────────────────────────────────────────────────
HELP = """
Commands:
  ask        — structured ask with domain selection
  outcome    — record the result of a past decision
  biography  — show Kroniqo's full biography
  backends   — list backends and key status
  switch     — change active backend
  quit       — exit

Or just TYPE ANYTHING to chat naturally.
Paste any API key or Telegram token to configure automatically.
"""

if __name__ == "__main__":
    _start_telegram_thread()
    backend = DEFAULT_BACKEND

    print("╔══════════════════════════════════════╗")
    print("║   Kroniqo Agent                      ║")
    print("╚══════════════════════════════════════╝")
    tg = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    print(f"Telegram : {'running in background' if tg else 'not configured — type: setup telegram'}")
    print(f"Backend  : {backend.upper()}")
    print("Type to chat, or 'help' for commands.\n")

    while True:
        try:
            user_input = input("kroniqo> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye."); break

        if not user_input: continue
        first_word = user_input.split()[0].lower()

        if first_word == "ask":
            domain = input("  Domain: ").strip() or "general"
            task = input("  Task: ").strip()
            if task: ask(domain, task, backend)

        elif first_word == "outcome":
            parts = user_input.split()
            if len(parts) >= 3:
                try:
                    did = int(parts[1])
                    outcome = parts[2].lower().split("/")[0]
                    mag = parts[3] if len(parts) > 3 else "medium"
                    if outcome not in ("correct", "wrong", "partial"):
                        print("  Use: correct, wrong, or partial")
                    else:
                        record_outcome(did, outcome, mag)
                        print(f"  Recorded {did} as {outcome}. Kroniqo aged.\n")
                except (ValueError, IndexError):
                    print("  Usage: outcome <id> <correct/wrong>")
            else:
                try:
                    did = int(input("  Decision ID: ").strip())
                    outcome = input("  Outcome (correct/wrong/partial): ").strip()
                    mag = input("  Magnitude [medium]: ").strip() or "medium"
                    notes = input("  Notes (optional): ").strip()
                    record_outcome(did, outcome, mag, notes)
                    print("  Recorded. Kroniqo aged.\n")
                except ValueError:
                    print("  Invalid ID.")

        elif first_word == "biography": show_biography()
        elif first_word == "backends": show_backends(backend)
        elif first_word == "switch":
            show_backends(backend)
            choice = input("  Choose backend: ").strip().lower()
            if choice in BACKENDS:
                backend = choice; print(f"  Switched to {backend.upper()}\n")
            else:
                print(f"  Unknown. Options: {list(BACKENDS.keys())}")
        elif first_word in ("quit", "exit", "q"):
            print("Goodbye."); break
        elif first_word == "help":
            print(HELP)
        else:
            if not handle_setup_intent(user_input):
                domain = detect_domain(user_input)
                print(f"  [auto-domain: {domain}]")
                try: ask(domain, user_input, backend)
                except RuntimeError: pass
