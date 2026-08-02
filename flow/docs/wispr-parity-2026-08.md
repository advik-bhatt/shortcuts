# Wispr Flow parity: research, sourcing, and build decisions (Aug 2, 2026)

The task: make flow ALL of Wispr Flow (the Basic + Pro tiers), source every
backend API it needs with real prices, rebuild anything that costs too much,
and ship shortcuts that outclass Wispr's — block-programmable, spoken-slot,
context-aware. This file records what was verified, from where, and which
build calls were made on that evidence.

**Verification state, honestly.** The planned 12-agent adversarial research
workflow (6 sourced recon passes, 6 refuters) died on a session usage limit
before returning anything; the research below was done inline in the same
session with targeted primary-source fetches instead. Facts marked
**[primary]** were read from the vendor/repo's own page; facts marked
**[aggregator]** come from multiple independent secondary sources that agree
with each other, with the primary page unreachable through this session's
proxy (wisprflow.ai itself, groq.com/pricing, docs.anthropic.com all 403'd).
Nothing below is from memory alone.

## 1. Wispr Flow, as of mid-2026

Tiers and prices — Basic: free, ~2,000 words/week on desktop (~1,000/week on
iPhone); Pro: $15/user/month, $12/month billed annually; 14-day Pro trial.
**[aggregator: eesel.ai/blog/wispr-flow-pricing, droidcrunch.com/wispr-flow-review,
voicescriber.com/wispr-flow-pricing-review, weesperneonflow.ai 2026-06-27]**

Feature set (union of Basic/Pro as marketed): dictation in any app,
auto-edits (punctuation, filler removal), tone matching / context awareness,
personal dictionary (free tier), 100+ languages, privacy mode, snippets
(Pro; team-shareable), Command Mode — voice-edit highlighted text, Pro,
desktop only — mobile keyboard apps (iOS; Android unlimited as a promo),
priority support and team admin on higher tiers. **[same aggregators]**

What their snippets are: saved expansions fired by phrase. No slots captured
from speech, no conditions, no actions — that is the gap this build drives
through.

## 2. flow v0.2 against that list

| Wispr feature | flow v0.2 | Notes |
| --- | --- | --- |
| Dictate anywhere | yes (macOS) | pipeline runs anywhere; capture/paste mac-only |
| Auto edits | yes | polish pass + "scratch that" handling (since v0.1) |
| Tone matching | yes, measurable | deterministic per-conversation register profile (`flow/style.py`), unit-tested; not a vibe, a count |
| Personal dictionary | yes | biases ASR prompt AND polish (since v0.1) |
| 100+ languages | inherited from Whisper large-v3 | plus the Hindi/Hinglish script brain Wispr lacks |
| Snippets | **outclassed** | block programs: spoken slots, if app/contact/time, transforms, URL/app/keys/shell actions, inline or whole-utterance |
| Command Mode (voice-edit selection) | yes | edit hotkey, any app, Cmd-C selection grab |
| Word caps | none | your keys, your machine |
| Windows / iPhone | **no** | honest gap; Wispr wins platform breadth |
| Price | ~$1.70/mo hosted, $0 local | vs $15/mo |

New beyond parity: tap-to-lock hands-free dictation; `flow try` dry runs;
the `flow blocks` visual editor; the fully-local mode.

## 3. Backend APIs, sourced and priced

ASR (the pipeline is OpenAI-`/audio/transcriptions`-compatible, so all of
these are interchangeable via `FLOW_ASR_BASE_URL`):

| Provider | Price | Status |
| --- | --- | --- |
| Groq whisper-large-v3-turbo | $0.04/audio-hour, 10s minimum per request | **default.** [aggregators agreeing: cloudzero, eesel, speechall, tokenmix; groq.com blog confirms the model lineup — pricing page 403'd] |
| Groq whisper-large-v3 | $0.111/audio-hour | accuracy upgrade, still trivial [same] |
| OpenAI whisper-1 | $0.006/min = $0.36/hour | ~9x Groq turbo [tokenmix + OpenAI docs cited therein] |

Polish/assist LLM: claude-haiku-4-5 at $1 in / $5 out per MTok
**[primary-adjacent: anthropic.com/news/claude-haiku-4-5 surfaced in search
with the price; platform.claude.com pricing page in the same results]**.
A dictation's polish call is ~1K tokens in, ~50 out ≈ $0.001.

Monthly math at 50 dictations/day: ASR ~$0.17 + polish ~$1.50 ≈ **$1.70/month**.
The smart-shortcut match adds one similarly-priced call only on gated
utterances. "If those cost too much" was the brief — they don't, but the
rebuild shipped anyway (next section) because $0 and offline beats cheap.

## 4. The rebuild: local ASR

whisper.cpp ships `whisper-server`, "HTTP transcription server with OAI-like
API"; default endpoint `/inference`, remappable via `--inference-path`, with
`--convert` only needed for non-WAV input — flow's recorder already emits the
16 kHz mono WAV it wants. **[primary: github.com/ggml-org/whisper.cpp +
examples/server]** So local mode is: `whisper-server --inference-path
/v1/audio/transcriptions -m ggml-large-v3-turbo-q5_0.bin`, and the existing
client just points at 127.0.0.1. Model ggml-large-v3-turbo-q5_0 (~574 MB)
from the canonical ggerganov/whisper.cpp conversions on Hugging Face.
`flow local setup` automates binary check, model download, config flip;
the daemon starts/reuses the server itself. Cost: $0. Data leaving the
machine: none.

Not chosen: faster-whisper (Python/CTranslate2 — a second heavy runtime),
mlx-whisper (no bundled HTTP server), Vosk (weaker code-switching than
large-v3), parakeet ports (English-centric; the Hindi bar rules them out).
These were to be adversarially compared by the dead workflow; the whisper.cpp
call rests on the primary-source server docs plus the hard requirement
(Hindi+English in one model = Whisper large-v3 family) that none of the
alternatives clearly meet.

## 5. Build decisions on the shortcut engine

- **Whole-utterance matching for commands, explicit `inline` for snippets.**
  The one unforgivable failure mode is a shortcut firing inside ordinary
  dictation. Deterministic first; the LLM paraphrase assist runs only when
  the deterministic layer found nothing, only on short utterances sharing a
  content word with a trigger (stopwords excluded), answers below a 0.8
  confidence floor fall through, and its output is re-validated against the
  real shortcut before anything executes. Every gate fails closed into
  dictation.
- **Hand-rolled block editor, not Blockly.** Our language is 13 block types;
  Blockly is a ~large vendored dependency and a build step, against a repo
  whose engine core is deliberately dependency-free. One self-contained HTML
  file, stdlib server, `X-Flow` header on the API (custom header forces a
  CORS preflight the server never grants — closes the classic
  localhost-tool CSRF/DNS-rebinding hole). Verified by driving it in real
  Chromium: palette-built shortcut, saved JSON, reload, try-panel fire, zero
  console errors.
- **The generative line.** Blocks compose text the user wrote (templates) or
  spoke (slots); edit mode executes the user's spoken instruction on the
  user's own text and its prompt forbids adding content the instruction
  didn't dictate. No block, mode, or prompt writes words for anyone. This is
  the house law (knowledge-base CLAUDE.md, "Never write anyone's words for
  them") applied as product architecture, and it is the honest contrast with
  Wispr-class "AI edits" drifting toward ghostwriting.
- **Shell blocks default-dead** (`allow_shell` opt-in) so a shared shortcut
  file can't run commands on someone else's machine.

## 6. Owed / next verification

- Live end-to-end on a real Mac (mic, permissions, whisper-server cold-start
  latency, edit-mode Cmd-C timing across apps) — this session is headless
  Linux; everything OS-bound is stubbed and covered by the off-mac paths.
- The Groq price and the whisper-server flag set should be re-read from
  groq.com/pricing and the repo README on a network that doesn't 403 them,
  before any of these numbers reach public copy.
- superwhisper / Talon / espanso feature-by-feature comparison (the dead
  workflow's recon pass) if the shortcut engine's next iteration wants
  stealable ideas: Talon's grammar captures and espanso's forms are the two
  systems worth reading first.

93 unit tests green at commit time; CLI drives recorded in the repo history
(commit message carries the evidence lines).
