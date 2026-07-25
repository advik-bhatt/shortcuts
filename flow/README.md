# flow — dictation that knows what language you're speaking

Hold a key. Talk — in English, in Hindi, in the mid-sentence mix of both. Release.
The text lands in whatever app is in front, punctuated like a human typed it,
with the Hindi written in the script *that conversation* uses — Devanagari for
one person, romanized Hinglish for another — without you ever saying which.

This is the Wispr Flow replacement: same push-to-talk dictation, same
"quotes and punctuation appear without being spoken" formatting, plus the thing
Wispr fumbles — automatic Hindi/Hinglish handling driven by context — at
roughly a tenth of Wispr's $15/month.

## How it decides the language (the actual point of this tool)

Every dictation runs a three-layer decision, and every layer is context-fed:

1. **The ASR layer already knows.** Whisper-class models transcribe Hindi
   speech in Devanagari and English in Latin script, so the transcript itself
   says what was spoken. Better: Whisper's `prompt` parameter biases its
   output style, so when flow already knows this conversation is written in
   romanized Hinglish, it primes the transcription with a romanized-Hindi
   sample *before* recognition runs — the same trick, one layer earlier, that
   Wispr's formatting engine does after the fact.

2. **A deterministic brain picks the script** (`flow/language.py`). Which
   script Hindi should come out in is a property of the *conversation*, not
   the utterance — you write to your mother in Devanagari and to the group
   chat in Latin letters. flow reads the frontmost app and window title
   (WhatsApp/Messages/Slack/Discord titles carry the person or channel name),
   looks up what script this exact conversation used before, and applies it.
   No preference yet? It mirrors the script you spoke in and starts learning.
   Every dictation updates the memory, so the second message to anyone is
   already automatic. All of it is unit-tested, dependency-free logic — no
   model in the loop for the decision itself.

3. **A Claude polish pass does the typing** (`flow/polish.py`). It gets the
   raw transcript, the target language/script, the app, the person, your last
   few dictations in that conversation, and your dictionary of proper nouns —
   then produces exactly the text to paste: inferred punctuation and quotation
   marks, "scratch that" self-edits honored, fillers dropped, Hindi
   transliterated into the chosen script (never translated), English words
   left in Latin, plain-ASCII mode when the front app is a code editor.

Layer 2's memory lives in plain local files (`~/.flow/prefs.json`,
`~/.flow/history.jsonl`). Nothing about your conversations is stored anywhere
else, and you can read or delete both files any time.

## Setup (macOS)

```bash
brew install portaudio
cd flow && pip install .

export GROQ_API_KEY=...        # ASR — console.groq.com, free tier is plenty to start
export ANTHROPIC_API_KEY=...   # polish pass

flow doctor                    # checks keys, deps, permissions
flow                           # hold right-Option, speak, release
```

Grant your terminal app **Microphone**, **Accessibility**, and **Input
Monitoring** in System Settings → Privacy & Security (doctor reminds you).

No `ANTHROPIC_API_KEY`? flow still works with a deterministic cleanup instead
of the polish pass. No `GROQ_API_KEY`? Set `OPENAI_API_KEY` and it uses
OpenAI's ASR instead, or point `FLOW_ASR_BASE_URL` at any OpenAI-compatible
transcription endpoint.

## Try the pipeline without a microphone

```bash
flow decide "haan theek hai kal milte hain"        # just the language/script call
flow text "bhai deploy karo aur phir mujhe batao" --app WhatsApp --contact Rohan
flow wav recording.wav                             # transcribe + polish a file
flow history                                       # what you've dictated lately
```

## Cost

Per dictation (~10s of speech, lean prompt), at list prices as of Jul 2026:

| Piece | Provider | Cost |
| --- | --- | --- |
| Transcription | Groq whisper-large-v3-turbo (~$0.04/audio-hour) | ~$0.0001 |
| Polish | claude-haiku-4-5 ($1/$5 per MTok) | ~$0.001 |

Call it **a tenth of a cent per dictation**: 50 dictations a day ≈
**$1.70/month**. Heavy use (100/day) ≈ $3.40/month. Wispr Flow is $15/month.

Want maximum polish quality instead of maximum cheap? `FLOW_MODEL=claude-sonnet-5`
roughly triples the polish cost — still ~$5–10/month at heavy use — and is
meaningfully better at subtle Hinglish transliteration. The default honors
"cheapest possible"; the env var honors "don't mess up."

## Configuration

Environment variables (or the same keys in `~/.flow/config.json`):

| Variable | Default | Meaning |
| --- | --- | --- |
| `FLOW_HOTKEY` | `alt_r` | push-to-talk key (pynput name: `alt_r`, `cmd_r`, `f13`, ...) |
| `FLOW_MODEL` | `claude-haiku-4-5` | polish model |
| `FLOW_HINDI_SCRIPT` | `mirror` | script when nothing is known yet: `mirror`, `devanagari`, `latin` |
| `FLOW_ASR_MODEL` | `whisper-large-v3-turbo` | ASR model (`whisper-large-v3` = more accurate, ~3× ASR cost, still trivial) |
| `FLOW_ASR_BASE_URL` | Groq | any OpenAI-compatible endpoint |
| `FLOW_DIR` | `~/.flow` | where history/prefs/config/dictionary live |

Put proper nouns one-per-line in `~/.flow/dictionary.txt` (Rolemate,
Trackathon, people's names) — they bias both the ASR and the polish pass, which
is where dictation tools usually mangle things.

## Honest limitations (v0.1)

- macOS-first. The pipeline (`text`/`wav`/`decide`) runs anywhere; capture and
  paste are mac-only for now.
- Push-to-talk key can't be the bare `fn` key (macOS doesn't expose it to
  userspace listeners) — right-Option is the default for a reason.
- Paste-into-app uses the clipboard (only reliable way to deliver Devanagari);
  the previous clipboard is saved and restored, but a clipboard manager may
  log the transit.
- Contact detection reads window titles, so it works where titles carry the
  chat name (WhatsApp, Messages, Telegram, Signal, Slack, Discord). Elsewhere
  it falls back to per-app memory.
- Audio goes to the ASR provider you configured; the polish transcript goes to
  Anthropic. Both are per-request API calls under your own keys — no
  subscription, no third-party training on your data per both providers' API
  terms — but it is not local-only. A fully local mode (whisper.cpp) is the
  obvious next step if that ever matters.

## Roadmap

- whisper.cpp local mode: $0.00/month, nothing leaves the machine.
- A tap-to-lock (hands-free) mode alongside hold-to-talk.
- Read the *other side* of the conversation (Accessibility API) so the very
  first message to someone new already matches their script.
- Menu-bar app wrapper + launchd agent so it starts on login.
