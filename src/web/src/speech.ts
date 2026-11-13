// Speech in the client: what an answer sounds like, recording a turn, reading aloud and the sounds of
// hands-free mode (UX-005, API-006, ADR-0088).
import { API_BASE, ApiError, REQUEST_HEADER, type Problem } from "./api/client";

/** What is said in place of what is not read out, in the user's language. */
export interface SpokenNames {
  code: string;
  table: string;
  image: string;
  diagram: string;
}

// The longest text one synthesis takes, and the first piece's, which the reading waits for (ADR-0088).
export const PIECE_CHARS = 4000;
export const FIRST_PIECE_CHARS = 300;

/** An answer's Markdown as it is read aloud: prose as it is, the rest named (ADR-0088). */
export function speakable(markdown: string, names: SpokenNames): string {
  const blocks: string[] = [];
  const lines = markdown.replace(/\r\n?/g, "\n").split("\n");
  let paragraph: string[] = [];
  const flush = () => {
    if (paragraph.length > 0) blocks.push(paragraph.join("\n"));
    paragraph = [];
  };
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index] ?? "";
    const fence = /^\s*(```+|~~~+)\s*([\w-]*)/.exec(line);
    if (fence) {
      flush();
      const close = fence[1] ?? "```";
      while (index + 1 < lines.length && !(lines[index + 1] ?? "").trim().startsWith(close)) index += 1;
      index += 1;
      blocks.push(fence[2] === "mermaid" ? names.diagram : names.code);
      continue;
    }
    if (/^\s*\|.*\|\s*$/.test(line)) {
      flush();
      while (index + 1 < lines.length && /^\s*\|.*\|\s*$/.test(lines[index + 1] ?? "")) index += 1;
      blocks.push(names.table);
      continue;
    }
    if (/^\s*!\[[^\]]*\]\([^)]*\)\s*$/.test(line)) {
      flush();
      blocks.push(names.image);
      continue;
    }
    if (line.trim() === "") {
      flush();
      continue;
    }
    paragraph.push(inline(line));
  }
  flush();
  return blocks.filter((block) => block.trim() !== "").join("\n\n");
}

/** One line of prose without its Markdown: headings, emphasis, code spans, links and list marks. */
function inline(line: string): string {
  return line
    .replace(/^\s{0,3}#{1,6}\s+/, "")
    .replace(/^\s*>\s?/, "")
    .replace(/^\s*(?:[-*+]|\d+[.)])\s+/, "")
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/<?https?:\/\/(?:www\.)?([^/\s>]+)[^\s>]*?>?(?=[\s.,;:!?)]*(?:\s|$))/g, "$1")
    .replace(/(\*\*|__)(.+?)\1/g, "$2")
    .replace(/(\*|_)(.+?)\1/g, "$2")
    .replace(/~~(.+?)~~/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .trim();
}

/**
 * A text in pieces of at most `limit` characters, the first of at most `first`, cut at paragraphs, then
 * sentences, then spaces.
 */
export function pieces(text: string, limit: number = PIECE_CHARS, first: number = limit): string[] {
  const result: string[] = [];
  let current = "";
  const room = () => (result.length === 0 ? first : limit);
  const add = (part: string, separator: string) => {
    if (current === "") current = part;
    else if (current.length + separator.length + part.length <= room()) current += separator + part;
    else {
      result.push(current);
      current = part;
    }
  };
  for (const paragraph of text.split(/\n{2,}/).map((part) => part.trim()).filter(Boolean)) {
    if (paragraph.length <= room()) {
      add(paragraph, "\n\n");
      continue;
    }
    for (const sentence of paragraph.match(/[^.!?]+[.!?]+["')\]]*|[^.!?]+$/g) ?? [paragraph]) {
      let rest = sentence.trim();
      while (rest.length > room()) {
        const cut = rest.lastIndexOf(" ", room());
        const at = cut > 0 ? cut : room();
        add(rest.slice(0, at).trim(), " ");
        rest = rest.slice(at).trim();
      }
      if (rest) add(rest, " ");
    }
  }
  if (current) result.push(current);
  return result;
}

async function problemOf(response: Response): Promise<ApiError> {
  const problem = (await response.json().catch(() => ({}))) as Partial<Problem>;
  return new ApiError(response.status, problem.code ?? "internal.error", problem);
}

/** The text of a recorded turn, from the household's transcription model. */
export async function transcribe(recording: Blob): Promise<string> {
  const form = new FormData();
  const extension = recording.type.includes("ogg") ? "ogg" : recording.type.includes("mp4") ? "mp4" : "webm";
  form.append("audio", recording, `turn.${extension}`);
  const response = await fetch(`${API_BASE}/speech/transcriptions`, { method: "POST", body: form, headers: REQUEST_HEADER, credentials: "same-origin" });
  if (!response.ok) throw await problemOf(response);
  return ((await response.json()) as { text: string }).text;
}

/** One piece of text as audio, from the household's speech model. */
export async function synthesize(text: string, signal?: AbortSignal): Promise<Blob> {
  const response = await fetch(`${API_BASE}/speech/synthesis`, {
    method: "POST",
    body: JSON.stringify({ text }),
    headers: { ...REQUEST_HEADER, "Content-Type": "application/json" },
    credentials: "same-origin",
    signal: signal ?? null,
  });
  if (!response.ok) throw await problemOf(response);
  return response.blob();
}

/** A recording of the microphone, from start to stop. */
export class Recorder {
  private recorder: MediaRecorder | null = null;
  private chunks: Blob[] = [];

  async start(): Promise<void> {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    const type = ["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/mp4"].find((candidate) => MediaRecorder.isTypeSupported(candidate));
    this.chunks = [];
    this.recorder = new MediaRecorder(stream, type ? { mimeType: type } : undefined);
    this.recorder.ondataavailable = (event) => {
      if (event.data.size > 0) this.chunks.push(event.data);
    };
    this.recorder.start(250);
  }

  get recording(): boolean {
    return this.recorder?.state === "recording";
  }

  /** The microphone's sound while it records, to show it. */
  get stream(): MediaStream | null {
    return this.recorder?.stream ?? null;
  }

  /** The recording so far; the microphone is released. */
  stop(): Promise<Blob> {
    const recorder = this.recorder;
    this.recorder = null;
    if (recorder === null) return Promise.resolve(new Blob());
    return new Promise((resolve) => {
      recorder.onstop = () => {
        for (const track of recorder.stream.getTracks()) track.stop();
        resolve(new Blob(this.chunks, { type: recorder.mimeType || "audio/webm" }));
      };
      recorder.stop();
    });
  }
}

// Silence before the first piece: an idle audio output, often Bluetooth, wakes up during it instead of
// swallowing the first word.
const LEAD_IN_SECONDS = 0.35;

/** Where a reading is: which piece is being prepared, or read, of how many. */
export interface ReadingStep {
  phase: "preparing" | "reading";
  part: number;
  total: number;
}

/** Reads a text aloud piece by piece, asking for the next piece while one plays. */
export class Reader {
  private abort = new AbortController();
  private source: AudioBufferSourceNode | null = null;
  private stopped = false;

  /** Read `text` aloud, saying through `progress` which piece is being prepared or read. */
  async read(text: string, progress?: (step: ReadingStep) => void): Promise<void> {
    const audio = output();
    await audio.resume();
    const parts = pieces(text, PIECE_CHARS, FIRST_PIECE_CHARS);
    let next = parts.length > 0 ? synthesize(parts[0] ?? "", this.abort.signal) : null;
    for (let index = 0; index < parts.length && next !== null && !this.stopped; index += 1) {
      progress?.({ phase: "preparing", part: index + 1, total: parts.length });
      const blob = await next;
      next = index + 1 < parts.length ? synthesize(parts[index + 1] ?? "", this.abort.signal) : null;
      if (this.stopped) break;
      let buffer: AudioBuffer;
      try {
        buffer = await audio.decodeAudioData(await blob.arrayBuffer());
      } catch {
        throw new Error("audio.unplayable");
      }
      if (this.stopped) break;
      progress?.({ phase: "reading", part: index + 1, total: parts.length });
      await this.play(audio, buffer, index === 0 ? LEAD_IN_SECONDS : 0);
    }
  }

  private play(audio: AudioContext, buffer: AudioBuffer, delay: number): Promise<void> {
    const source = audio.createBufferSource();
    source.buffer = buffer;
    source.connect(audio.destination);
    this.source = source;
    return new Promise((resolve) => {
      source.onended = () => {
        this.source = null;
        resolve();
      };
      source.start(audio.currentTime + delay);
    });
  }

  stop(): void {
    this.stopped = true;
    this.abort.abort();
    try {
      this.source?.stop();
    } catch {
      // Not started yet, or already ended.
    }
  }
}

let context: AudioContext | null = null;

/** The page's audio output, shared by the reading and the sounds. */
function output(): AudioContext {
  context ??= new AudioContext();
  return context;
}

export type Cue = "start" | "end" | "tick" | "answer" | "error";

// Each sound: its notes, in hertz, and how long each lasts, in seconds (ADR-0088).
const CUES: Record<Cue, { notes: number[]; length: number; volume: number }> = {
  start: { notes: [660, 990], length: 0.09, volume: 0.25 },
  end: { notes: [880, 587], length: 0.09, volume: 0.25 },
  tick: { notes: [1320], length: 0.03, volume: 0.07 },
  answer: { notes: [784, 1047, 1319], length: 0.08, volume: 0.2 },
  error: { notes: [220, 196], length: 0.18, volume: 0.25 },
};

/** Play one of hands-free mode's sounds. */
export function playCue(cue: Cue): void {
  try {
    const context = output();
    void context.resume();
    const { notes, length, volume } = CUES[cue];
    let at = context.currentTime + 0.01;
    for (const frequency of notes) {
      const oscillator = context.createOscillator();
      const gain = context.createGain();
      oscillator.type = "sine";
      oscillator.frequency.value = frequency;
      gain.gain.setValueAtTime(0, at);
      gain.gain.linearRampToValueAtTime(volume, at + 0.01);
      gain.gain.exponentialRampToValueAtTime(0.0001, at + length);
      oscillator.connect(gain).connect(context.destination);
      oscillator.start(at);
      oscillator.stop(at + length + 0.02);
      at += length;
    }
  } catch {
    // A device without audio has no sounds to play.
  }
}

/** A second of silence, as a WAV file: playing it in a loop gives the page the media buttons. */
export function silenceUrl(): string {
  const rate = 8000;
  const samples = rate;
  const buffer = new ArrayBuffer(44 + samples);
  const view = new DataView(buffer);
  const write = (offset: number, text: string) => [...text].forEach((char, index) => view.setUint8(offset + index, char.charCodeAt(0)));
  write(0, "RIFF");
  view.setUint32(4, 36 + samples, true);
  write(8, "WAVEfmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, rate, true);
  view.setUint32(28, rate, true);
  view.setUint16(32, 1, true);
  view.setUint16(34, 8, true);
  write(36, "data");
  view.setUint32(40, samples, true);
  for (let index = 0; index < samples; index += 1) view.setUint8(44 + index, 128);
  return URL.createObjectURL(new Blob([buffer], { type: "audio/wav" }));
}
