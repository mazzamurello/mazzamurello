# ADR-0088: Speech through connections, and a hands-free mode

- **Status:** Accepted
- **Date:** 2026-11-10
- **Deciders:** @tapionx
- **Related:** ADR-0040, ADR-0042, ADR-0057, ADR-0066, ADR-0069, UX-005, API-006, MOD-003, MOD-006, MOD-010

## Context

ADR-0040 made voice a matter of explicit turns, with speech services local by
default. Two things have changed since.

Speech models are now served the way chat models are. OpenRouter offers
transcription at `/audio/transcriptions` and speech at `/audio/speech`, both
OpenAI-compatible, and lists those models with the others, telling them
apart by their output modalities, `transcription` and `speech`, with the
voices of each. Local servers of open models, such as speaches or LocalAI,
expose the same two endpoints. The local voices that run on the hardware
most households have, a mini PC without a GPU, sound clearly worse than the
remote ones, so a household must be able to choose either, as it does for
chat models.

A user who brainstorms while driving cannot look at the screen or aim at a
small button. Cars and headsets have media buttons, which browsers pass to
the page that plays audio through the Media Session API.

## Decision

1. **Speech models come from connections.** Each model a connection lists
   has a kind: `chat`, `transcription` or `speech`, and a speech model its
   voices. OpenRouter's list says which is which, and its voices
   (`supported_voices`). An OpenAI-compatible server's list says neither, so
   its models get their kind from their names (`whisper`, `transcribe`,
   `parakeet` or `stt` for transcription; `tts`, `speech`, `voice`, `kokoro`
   or `piper` for speech; chat otherwise), and a speech model of such a
   server has no listed voices: the admin types the voice's name. No speech
   server is bundled; the documentation shows how to run one and add it as
   a connection, as for a model server.
2. **The household chooses.** Tenant admins choose the household's
   transcription model, and its speech model with a voice, as they choose its
   default model. Without a transcription model, clients offer no spoken
   turns; without a speech model, no reading aloud.
3. **Endpoints.** `POST /speech/transcriptions` takes one recording, at
   most 25 MB, and returns its text; the recording is held in memory for the
   request only. `POST /speech/synthesis` takes at most 4,000 characters and
   returns the audio, as MP3. They reach the model with the connection's
   credentials, which stay in the control plane, and record their cost in
   the ledger with the purpose `speech`. OpenRouter's transcriptions report
   their cost; its speech does not. OpenRouter
   publishes speech prices, but in units that differ by model (characters,
   seconds or tokens) and that its list does not name, so the cost is not
   computed from them: it is the cost OpenRouter reports for the
   generation, asked for by the generation's ID once the audio is sent,
   and recorded then; until it is known, the entry has no cost.
4. **Reading aloud.** The client turns an answer's Markdown into what is
   said: prose as it is, a code block, table, image or diagram named in a
   sentence of the user's language, a link by its text. It splits the text
   at paragraphs and sentences into requests and plays them in turn, asking
   for the next while one plays. The first piece is short, at most 300
   characters, since the reading waits for it; the others take up to 4,000.
   A speech model takes seconds for a long text, so speech requests may take
   two minutes before they fail as too slow, whatever the connection's
   address; a connection test's twenty seconds are for listing models.
   A failed request says why in its problem's `detail`, which hands-free
   mode shows with the step that failed.
5. **Three ways to speak.** Dictation puts the transcription in the message
   box. Reading aloud is offered on every answer. Hands-free mode fills the
   conversation with one large button: a press starts the user's turn, the
   next ends it and sends it, and the complete answer is then read aloud.
   When the reading ends, the next turn starts by itself, with the sound of
   a turn starting, so that a conversation goes on without a press for each
   turn; a press while it reads stops the reading and starts the next turn
   at once. A failure ends the conversation's flow: the next turn waits for
   a press. Silence never ends a turn (ADR-0040).
6. **The assistant knows how the turn came.** A run carries `voice`:
   `dictated` when the message was dictated, even in part, and `hands_free`
   when it was spoken in hands-free mode. The instructions of that run say
   so after the working instructions: a dictated message may hold words a
   transcription model misheard, which the assistant reads for what was
   meant; an answer in hands-free mode will be read aloud, so it is written
   for listening, in sentences rather than tables, lists or code, unless
   the user asks for them, without being shorter or simpler (ADR-0040). The
   transcription is never rewritten before it is sent. While the user
   dictates, the message box shows bars that rise and fall with the
   loudness of the voice, so that the user sees the microphone works, with
   a stop button, then that the text is being prepared; the large button of
   hands-free mode shows the same bars while it listens.
7. **Media buttons.** In hands-free mode the client plays a silent sound, so
   that the device gives it the media buttons, and acts on next track, play
   and pause as on the large button; on devices with a keyboard, its media
   keys do the same.
8. **Sounds.** Short tones, made by the client: rising when the user's turn
   starts, played before the microphone opens, since a phone may quiet its
   speaker while it opens it, falling when it ends, a soft tick every few seconds while the
   assistant works, a chime before the answer is read, and a low tone when
   something fails.
9. **Languages.** The transcription model detects the language of the turn;
   the reading uses the household's voice, whose languages depend on its
   model.

This amends decision 1 of ADR-0040, in hands-free mode only: a turn starts
by itself once the answer before it is read. It also amends decision 5 of
ADR-0040: speech is local when the household's connections are, and
otherwise passes through the data egress policy like any remote model.

## Consequences

- A household picks speech the way it picks chat models: a local server for
  privacy, or OpenRouter for the best voices, with nothing to install.
- The quality of a household's voice is its connection's; the project ships
  no models and no speech server of its own.
- Hands-free mode relies on the device passing media buttons to the browser.
  Where it does not, as on some cars while the microphone is in use, the
  large button remains. A phone must stay unlocked with the app open: a web
  app stops recording when the screen locks.
- One voice per household; a voice for each user may follow.
- Synthesized speech from OpenRouter is recorded with its cost a moment
  after it plays, as OpenRouter reports it for the generation.
- The instructions change with the way a turn came, which costs a little
  of the provider's prompt cache on that turn.
- Hands-free mode shows the sprite in its upper half, with a pose of its own
  for listening.

## Alternatives considered

- **A bundled speech service:** the open voices that run on a mini PC are
  not good enough to be the default, and a bundled service would cost every
  household its memory and disk whether it speaks or not.
- **Speech settings separate from connections:** a second way to add
  providers, keys and addresses, for the same providers.
- **A spoken word or a pause to end a turn:** a keyword spotter in every
  language, and a pause that interrupts people who think aloud (ADR-0040);
  the media buttons and the large button come first.
- **A press to start every turn in hands-free mode:** while driving, each
  press is one more look away from the road; listening again when the
  answer ends needs none, and the sound says that it listens.
- **Tidying a dictation with a chat model before showing it:** tried, and
  dropped: a second request's cost and seconds of waiting, for mistakes the
  model that answers reads past anyway once it knows the turn was dictated.
- **Streaming speech both ways:** needs real-time models, which few providers
  and no small local server offer.
