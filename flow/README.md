# flow — dictation that knows what language you're speaking, with shortcuts you program by voice

Hold a key. Talk — in English, in Hindi, in the mid-sentence mix of both. Release.
The text lands in whatever app is in front, punctuated like a human typed it,
with the Hindi written in the script *that conversation* uses — Devanagari for
one person, romanized Hinglish for another — without you ever saying which.

This is the whole Wispr Flow feature set, rebuilt on your own keys — and past
it: Wispr's snippets paste a saved string; flow's shortcuts are **small
programs you assemble from Scratch-style blocks** and fire by voice, with
spoken slots, per-app branching, and real actions. Wispr Pro is $15/month.
flow is ~$1.70/month on hosted APIs, or **$0 and fully offline** in local mode.

## What one dictation can do now

```
"email Sam about the launch timeline"     -> fires your email shortcut,
                                             person=Sam, topic=the launch timeline
"ship it to insert my address, thanks"    -> "Ship it to 12 Elm St, ..., thanks"
"standup note shipped the blocks editor"  -> "Standup 2026-08-02 — Shipped the blocks editor"
"open my calendar"                        -> types nothing, opens the calendar
bhai deploy karo aur phir mujhe batao     -> lands as Hinglish, in the script
                                             this chat already uses
```

And with text selected anywhere, hold the **edit key** and say "make that two
sentences" — the selection is replaced in place.

## The five layers

1. **ASR** — Whisper large-v3-turbo (hosted on Groq by default, or local
   whisper.cpp), primed with your dictionary and the conversation's script.
2. **The language brain** (`flow/language.py`) — deterministic, unit-tested
   Hindi/Hinglish/English + script decision, learned per (app, contact).
3. **The shortcut engine** (`flow/shortcuts.py`) — deterministic matcher and
   block interpreter, then an LLM assist for paraphrase ("shoot an email over
   to Sam re the launch" still fires `email <person> about <topic>`), gated so
   it can never touch ordinary dictation and re-validated before anything runs.
4. **The polish pass** (`flow/polish.py`) — Claude turns the raw transcript
   into what you meant to type: punctuation, "scratch that" edits, filler
   removal, transliteration into the right script, and **tone matching**
   measured from this exact conversation (lowercase chats stay lowercase).
5. **Delivery** (`flow/insert.py`, `flow/actions.py`) — paste into the
   frontmost app, then run any block actions (open URL/app, press keys).

## Shortcuts: Scratch-style blocks, spoken triggers

`flow blocks` opens the visual editor (localhost, one self-contained page,
works offline). Build a shortcut from blocks:

- **Triggers** — `"email <person> about <topic>"`: `<slot>` captures spoken
  words, `(word)` is optional, fillers like "um"/"please" are ignored. A
  command fires only when the WHOLE utterance matches, so dictating a sentence
  that merely contains the phrase never misfires. Mark a shortcut **inline**
  instead and it expands mid-dictation ("...to insert my address, thanks").
- **Content blocks** — your text, spoken slots, date/time, clipboard, your
  last dictation.
- **Logic blocks** — if app / contact / hour / weekday, and transforms
  (upper, sentence case, trim...). One sign-off that's "cheers" in Slack and
  "Best,\nAdvik" in Mail.
- **Action blocks** — open a URL (slots substitute: `cal.com/you?invite={person}`),
  launch an app, press a key combo, pause. Shell blocks exist but stay dead
  until you set `allow_shell` yourself.

Everything is a plain JSON file in `~/.flow/shortcuts/` — the editor is
optional, git-friendly hand-editing works, and `flow try "utterance"` shows
exactly what would fire, dry-run. Starters to copy: `examples/shortcuts/`.

One law, inherited from the house rule: **blocks compose words you wrote or
spoke. No block generates content on its own.** flow types for you; it never
talks for you.

## Setup (macOS)

```bash
brew install portaudio
cd flow && pip install .

export GROQ_API_KEY=...        # ASR — console.groq.com, free tier is plenty to start
export ANTHROPIC_API_KEY=...   # polish + smart shortcut matching + edit mode

flow doctor                    # checks keys, deps, permissions
flow                           # hold right-Option, speak, release; tap it to lock hands-free
flow blocks                    # the visual shortcut editor
```

Grant your terminal app **Microphone**, **Accessibility**, and **Input
Monitoring** in System Settings → Privacy & Security (doctor reminds you).

### The $0 local mode

```bash
brew install whisper-cpp
flow local setup               # downloads the model (~574 MB), flips config
flow                           # audio never leaves the machine
```

Local mode runs whisper.cpp's `whisper-server` with its endpoint remapped to
the OpenAI path (`--inference-path /v1/audio/transcriptions`), so the rest of
the pipeline can't tell the difference. The daemon starts and reuses the
server itself. Same Whisper large-v3 family, so Hindi + English code-switching
keeps working. No polish key on top of that? The deterministic cleanup runs
instead — fully offline dictation, zero dollars, exact-phrase shortcuts still on.

## Try the pipeline without a microphone

```bash
flow try "email Sam about the launch"              # dry-run: what would fire?
flow text "bhai deploy karo" --app WhatsApp --contact Rohan
flow shortcuts                                     # list triggers
flow wav recording.wav                             # transcribe + route + polish a file
flow history                                       # what you've dictated lately
```

## Cost (verified against provider pricing, Aug 2026)

Per dictation (~10s of speech, lean prompt), at list prices:

| Piece | Provider | Cost |
| --- | --- | --- |
| Transcription | Groq whisper-large-v3-turbo, $0.04/audio-hour (10s billing minimum) | ~$0.00011 |
| Polish | claude-haiku-4-5, $1 in / $5 out per MTok | ~$0.001 |
| Both, local mode | whisper.cpp + deterministic cleanup | $0 |

50 dictations a day ≈ **$1.70/month**. Heavy use (100/day) ≈ $3.40/month.
A smart-shortcut LLM match costs about the same as one polish call and only
runs on command-shaped utterances that share a word with your triggers.
Wispr Flow: free tier capped at ~2,000 words/week, Pro $15/month
($12/month annual). Full sourced comparison: `docs/wispr-parity-2026-08.md`.

`FLOW_MODEL=claude-sonnet-5` roughly triples polish cost — still ~$5–10/month
heavy — and is meaningfully better at subtle Hinglish transliteration.

## Configuration

Environment variables (or the same keys in `~/.flow/config.json`):

| Variable | Default | Meaning |
| --- | --- | --- |
| `FLOW_HOTKEY` | `alt_r` | push-to-talk key; tap instead of hold to lock hands-free |
| `FLOW_EDIT_HOTKEY` | `cmd_r` | hold on a selection, speak the change |
| `FLOW_MODEL` | `claude-haiku-4-5` | polish/assist model |
| `FLOW_SMART_MATCH` | `conservative` | LLM shortcut matching: `off`, `conservative`, `eager` |
| `FLOW_ALLOW_SHELL` | off | let shell blocks run |
| `FLOW_ASR_MODE` | `auto` | `auto`, `hosted`, `local` |
| `FLOW_HINDI_SCRIPT` | `mirror` | script when nothing is known: `mirror`, `devanagari`, `latin` |
| `FLOW_ASR_MODEL` | `whisper-large-v3-turbo` | hosted ASR model |
| `FLOW_ASR_BASE_URL` | Groq | any OpenAI-compatible endpoint |
| `FLOW_DIR` | `~/.flow` | history, prefs, config, dictionary, shortcuts, models |

Put proper nouns one-per-line in `~/.flow/dictionary.txt` (Rolemate,
Trackathon, people's names) — they bias both the ASR and the polish pass.

## Honest limitations (v0.2)

- macOS-first. The pipeline (`text`/`try`/`wav`/`decide`, the editor) runs
  anywhere; capture, paste, selection-grab, and actions are mac-only for now.
  No Windows or iPhone apps — Wispr still wins on platform breadth.
- Edit mode and smart (paraphrase) shortcut matching need `ANTHROPIC_API_KEY`;
  without it you keep dictation, exact-phrase shortcuts, and inline snippets.
- Edit mode grabs the selection by synthesizing Cmd-C (clipboard saved and
  restored) — the one approach that works across native, browser, and
  Electron apps alike, but a clipboard manager may log the transit.
- Push-to-talk can't be the bare `fn` key (macOS doesn't expose it); the
  right-Option default is deliberate.
- Contact detection reads window titles, so it works where titles carry the
  chat name (WhatsApp, Messages, Telegram, Signal, Slack, Discord).
- Hosted mode sends audio to your configured ASR provider and transcripts to
  Anthropic, per-request under your own keys. Local mode sends nothing anywhere.

## Roadmap

- Read the *other side* of the conversation (Accessibility API) so the very
  first message to someone new already matches their script.
- Menu-bar app wrapper + launchd agent so it starts on login.
- Per-shortcut usage stats in `flow blocks` (which triggers earn their keep).
- Piggyback shortcut intent onto the polish call (one round trip, not two).
