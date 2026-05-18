# Kroniqo

> *AI that doesn't just remember — it ages.*

---

## The Problem With AI Memory

Every AI agent today can be given memory. It recalls facts. It knows what you told it last session. But it has no **biography**.

Ask the same agent a question after it's been confidently wrong 9 times in a domain — it answers with the same bold confidence as if nothing happened. It remembered the facts. But it wasn't *changed* by the experience.

Humans don't work that way. A doctor who loses a patient doesn't just remember the case — they become a more careful thinker. A trader who blows up an account doesn't just recall the loss — they size down. Experience shapes character, not just recall.

**Kroniqo is the difference between memory and biography.**

---

## How It Works

Every decision Kroniqo makes is logged with its context and expressed confidence. After a human or automated judge verifies the outcome, it's written back to a **Consequence Graph** — a SQLite database that tracks not what happened, but what it means.

Before every new decision, Kroniqo consults its own biography. The behavioral modifier adjusts its system prompt dynamically:

- Domains where it's been consistently wrong → **conservative** posture, lower confidence, explicit uncertainty
- Domains where it's been consistently right → **bold** posture, decisive answers
- Recent failures weigh more than old victories (recency decay)

```
Decision Made
     │
     ▼
log_decision(domain, task, confidence)
     │
     ▼
Outcome Verified (human or auto-judge)
     │
     ▼
record_outcome(id, 'correct'/'wrong', magnitude)
     │
     ▼
Consequence Graph updates
  - Recency decay applied: weight = e^(-0.03 * days_ago)
  - Weighted accuracy recomputed per domain
  - Risk posture determined: conservative / neutral / bold
     │
     ▼
System Prompt injected with Biography before next decision
     │
     ▼
Kroniqo responds — shaped by experience, not just facts
```

---

## Memory vs Consequence Graph

| Memory | Consequence Graph |
|--------|-----------------|
| Recalls facts | Shapes behavior |
| "On March 3rd you said X" | "In logic, you were wrong 9/12 times" |
| Static retrieval | Dynamic adaptation |
| Tells you what happened | Tells you who you've *become* |

---

## Time is Measured in Scars

Kroniqo measures age in three layers:

1. **Chronological** — real timestamps on every event
2. **Experiential** — age = number of consequential decisions, not days
3. **Recency Decay** — `weight = e^(-0.03 * days_ago)` — last week matters more than last month

---

## It Works

After one wrong answer in the logic domain, Kroniqo was asked another logic question. Without being told to, it wrote:

> *"Given my track record in logic, I should be cautious and not overconfident in my answer."*

**CONFIDENCE: 0.2**

That sentence wasn't in the system prompt. Kroniqo generated it from its own biography. That's not memory. That's character formation.

---

## Features

- **Free chat mode** — just type naturally, domain auto-detected
- **Multi-backend** — Groq, Gemini, Cerebras, Claude, Mistral, GLM5
- **Automatic fallback chain** — if one backend fails, tries the next
- **Telegram bot** — full `/ask /debug /outcome /biography` interface
- **Code debug tool** — Kroniqo fixes code, runs it in subprocess, auto-records outcome
- **Batch debug** — point it at a folder of broken `.py` files, it ages automatically
- **Lightweight** — SQLite only, runs on phone via Termux

---

## Quick Start

```bash
git clone https://github.com/Jeff9497/Kroniq09.git
cd Kroniq09
pip install -r requirements.txt

# Set at least one backend key (Groq recommended — free, fast)
export GROQ_API_KEY=your_key      # console.groq.com — free, no credit card
export GEMINI_API_KEY=your_key    # aistudio.google.com — free, most generous

python kroniqo-agent/agent.py
```

---

## CLI Usage

```
kroniqo> tell me about quantum computing
  [auto-domain: science]
  ... answers ...
  Decision ID: 1

kroniqo> outcome 1 correct

kroniqo> biography
```

Or structured commands:
```
ask        — structured ask with domain selection
outcome    — record result of a past decision
biography  — show full biography and domain breakdown
backends   — show all backends and API key status
switch     — change active backend
```

---

## Telegram Bot

```bash
export TELEGRAM_BOT_TOKEN=your_token   # from @BotFather
export GROQ_API_KEY=your_key
python kroniqo-agent/telegram_bot.py
```

Commands: `/ask` `/debug` `/outcome` `/biography` `/backend` `/backends`

---

## Supported Backends

| Backend | Free Tier | Speed |
|---------|-----------|-------|
| Groq (Llama 3.3 70B) | 1,000 req/day | Fastest |
| Gemini 2.0 Flash | 1,500 req/day | Fast |
| Cerebras | 1M tokens/day | Fast |
| Mistral | 1B tokens/month | Good |
| Claude Sonnet | Paid | Best quality |

---

## Project Structure

```
Kroniq09/
├── kroniqo-core/
│   └── consequence_graph.py   # Aging engine — decay, biography, modifiers
├── kroniqo-agent/
│   ├── agent.py               # CLI + free chat + multi-backend
│   ├── telegram_bot.py        # Telegram interface
│   ├── tools/
│   │   └── code_runner.py     # Auto code debug + outcome recording
│   └── test_bugs/             # 5 broken Python files for batch testing
└── requirements.txt
```

---

## What's Next

- Auto-judge pipeline — math via Python eval, trivia via web search, logic via LLM judge
- Web dashboard — visualize biography, domain accuracy charts, aging over time
- Multi-agent — two Kroniqo instances debate, loser's biography takes the hit

---

## Stack

Python 3.11 · SQLite · Groq · Gemini · Anthropic API · python-telegram-bot

---

*Built by [Jeff9497](https://github.com/Jeff9497)*
