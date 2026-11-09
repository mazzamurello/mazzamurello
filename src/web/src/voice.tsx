// Voice turns: dictation, reading aloud, and hands-free mode with its large button, media buttons and
// sounds (UX-005, ADR-0088). Hands-free mode lives above the routes, so that a turn spoken on the
// new-chat screen carries on in the conversation it creates.
import { Headphones, LoaderCircle, Mic, Volume2, X } from "lucide-react";
import { createContext, type ReactNode, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError, type ModelOption } from "./api/client";
import { findModel, useModels } from "./models";
import { useNotify } from "./notices";
import { type Pose, Sprite } from "./components/Sprite";
import { VoiceLevel } from "./components/VoiceLevel";
import { type Cue, playCue, Reader, type ReadingStep, Recorder, silenceUrl, speakable, type SpokenNames, transcribe } from "./speech";

export type VoiceState = "idle" | "listening" | "transcribing" | "waiting" | "reading" | "failed";

/** Which step a hands-free turn is at, since when, and, while it is read, which piece (UX-005). */
export interface Step {
  kind: "listening" | "transcribing" | "writing" | "preparing" | "reading";
  since: number;
  part?: number;
  total?: number;
}

// How long the sound of a turn starting lasts, before the microphone opens, in milliseconds.
const CUE_MS = 260;
// How often the assistant says it is still working, in milliseconds.
const TICK_MS = 3000;
// The media buttons that act as the large button.
const MEDIA_ACTIONS: MediaSessionAction[] = ["nexttrack", "previoustrack", "play", "pause"];
const MEDIA_KEYS = new Set(["MediaTrackNext", "MediaTrackPrevious", "MediaPlayPause", "MediaPlay", "MediaPause"]);

// How a message came, when it was not typed: the assistant is told (ADR-0088).
export type VoiceMode = "dictated" | "hands_free";
type Sender = (text: string, voice: VoiceMode) => void;

interface Voice {
  transcription: ModelOption | undefined;
  speech: ModelOption | undefined;
  handsFree: boolean;
  state: VoiceState;
  cue: Cue | null;
  press: () => void;
  open: () => void;
  close: () => void;
  /** The message box that sends a hands-free turn: the one in view. */
  register: (sender: Sender) => () => void;
  /** The answer to the hands-free turn, or its failure. */
  answered: (markdown: string) => void;
  /** What the run in view is doing, for the sprite of hands-free mode (UX-013). */
  showRun: (pose: Pose) => void;
  runPose: Pose;
  /** The microphone's sound while a hands-free turn is open. */
  stream: MediaStream | null;
  /** The step the hands-free turn is at, and why the last one failed. */
  step: Step | null;
  failure: string | null;
  failed: () => void;
  /** Reading one answer aloud, outside hands-free mode. */
  reading: string | null;
  readAloud: (key: string, markdown: string) => void;
  stopReading: () => void;
}

const VoiceContext = createContext<Voice | null>(null);

export function useVoice(): Voice | null {
  return useContext(VoiceContext);
}

function useNames(): SpokenNames {
  const { t } = useTranslation();
  return useMemo(() => ({ code: t("voice.said.code"), table: t("voice.said.table"), image: t("voice.said.image"), diagram: t("voice.said.diagram") }), [t]);
}

export function VoiceProvider({ children }: { children: ReactNode }) {
  const models = useModels();
  const names = useNames();
  const settings = models.data?.speech;
  const transcription = findModel(models.data?.items, settings?.transcription);
  const speech = findModel(models.data?.items, settings?.speech);
  const [handsFree, setHandsFree] = useState(false);
  const [state, setState] = useState<VoiceState>("idle");
  const [cue, setCue] = useState<Cue | null>(null);
  const [reading, setReading] = useState<string | null>(null);
  const [runPose, setRunPose] = useState<Pose>("waiting");
  const [stream, setStream] = useState<MediaStream | null>(null);
  const [step, setStep] = useState<Step | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const { t } = useTranslation();
  const notify = useNotify();
  const begin = useCallback((kind: Step["kind"], part?: { part: number; total: number }) => {
    setFailure(null);
    setStep((now) => (now?.kind === kind && now.part === part?.part ? now : { kind, since: Date.now(), ...part }));
  }, []);
  // Why a step failed, in words the user can act on.
  const reasonOf = useCallback(
    (error: unknown) =>
      error instanceof ApiError
        ? typeof error.problem.detail === "string"
          ? error.problem.detail
          : t(`errors.${error.code.replace(".", "_")}`, { defaultValue: error.code })
        : error instanceof Error && error.message === "audio.unplayable"
          ? t("voice.errors.unplayable")
          : error instanceof Error && error.message === "voice.nothing"
            ? t("voice.errors.nothing")
            : error instanceof DOMException
              ? t("voice.errors.microphone")
              : error instanceof Error && error.message
                ? error.message
                : t("errors.internal_error"),
    [t],
  );
  const fail = useCallback((error: unknown) => {
    setFailure(reasonOf(error));
    stateRef.current = "failed";
    setState("failed");
    playCue("error");
    setCue("error");
  }, [reasonOf]);
  const senders = useRef<Sender[]>([]);
  const recorder = useRef(new Recorder());
  const reader = useRef<Reader | null>(null);
  const awaiting = useRef(false);
  const stateRef = useRef<VoiceState>("idle");
  const silence = useRef<HTMLAudioElement | null>(null);

  const go = useCallback((next: VoiceState, sound?: Cue) => {
    stateRef.current = next;
    setState(next);
    if (sound) {
      playCue(sound);
      setCue(sound);
    }
  }, []);

  const stopReading = useCallback(() => {
    reader.current?.stop();
    reader.current = null;
    setReading(null);
  }, []);

  const read = useCallback(
    async (markdown: string, progress?: (step: ReadingStep) => void): Promise<boolean> => {
      const current = new Reader();
      reader.current = current;
      try {
        await current.read(speakable(markdown, names), progress);
        return reader.current === current;
      } finally {
        if (reader.current === current) reader.current = null;
      }
    },
    [names],
  );

  const listen = useCallback(async () => {
    // The sound first: a phone may quiet its speaker while it opens the microphone (ADR-0088). Presses
    // meanwhile wait.
    stateRef.current = "waiting";
    playCue("start");
    await new Promise((resolve) => window.setTimeout(resolve, CUE_MS));
    try {
      await recorder.current.start();
      setStream(recorder.current.stream);
      stateRef.current = "listening";
      setState("listening");
      setCue("start");
      begin("listening");
    } catch (error) {
      fail(error);
    }
  }, [begin, fail]);

  // The large button, and the media buttons: start the turn, end it, or stop the reading and talk.
  const press = useCallback(async () => {
    const now = stateRef.current;
    if (now === "idle" || now === "failed") return listen();
    if (now === "reading") {
      stopReading();
      return listen();
    }
    if (now !== "listening") return;
    go("transcribing", "end");
    begin("transcribing");
    setStream(null);
    try {
      const said = (await transcribe(await recorder.current.stop())).trim();
      const send = senders.current.at(-1);
      if (!said || !send) throw new Error("voice.nothing");
      awaiting.current = true;
      go("waiting");
      begin("writing");
      send(said, "hands_free");
    } catch (error) {
      awaiting.current = false;
      fail(error);
    }
  }, [begin, fail, go, listen, stopReading]);

  const answered = useCallback(
    (markdown: string) => {
      if (!awaiting.current) return;
      awaiting.current = false;
      go("reading", "answer");
      begin("preparing", { part: 1, total: 1 });
      void read(markdown, (now) => begin(now.phase, { part: now.part, total: now.total }))
        .then((finished) => {
          // The conversation goes on: the next turn starts by itself, with its sound (ADR-0088).
          if (finished && stateRef.current === "reading") void listen();
        })
        .catch(fail);
    },
    [begin, fail, go, listen, read],
  );

  const failed = useCallback(() => {
    if (!awaiting.current) return;
    awaiting.current = false;
    fail(new Error(t("voice.errors.answer")));
  }, [fail, t]);

  const close = useCallback(() => {
    setHandsFree(false);
    awaiting.current = false;
    stopReading();
    void recorder.current.stop();
    go("idle");
    silence.current?.pause();
    silence.current = null;
  }, [go, stopReading]);

  const open = useCallback(() => {
    stopReading();
    setHandsFree(true);
    go("idle");
    // Playing silence gives the page the media buttons of a headset or a car (ADR-0088).
    const audio = new Audio(silenceUrl());
    audio.loop = true;
    audio.volume = 0.01;
    silence.current = audio;
    void audio.play().catch(() => undefined);
  }, [go, stopReading]);

  // The media buttons and keys, while hands-free mode is on.
  useEffect(() => {
    if (!handsFree) return;
    const session = "mediaSession" in navigator ? navigator.mediaSession : null;
    for (const action of MEDIA_ACTIONS) {
      try {
        session?.setActionHandler(action, () => {
          void silence.current?.play().catch(() => undefined);
          void press();
        });
      } catch {
        // An action this browser does not know.
      }
    }
    if (session && "MediaMetadata" in window) session.metadata = new MediaMetadata({ title: "Sibillo" });
    const key = (event: KeyboardEvent) => {
      if (!MEDIA_KEYS.has(event.key)) return;
      event.preventDefault();
      void press();
    };
    window.addEventListener("keydown", key);
    return () => {
      window.removeEventListener("keydown", key);
      for (const action of MEDIA_ACTIONS) {
        try {
          session?.setActionHandler(action, null);
        } catch {
          // As above.
        }
      }
    };
  }, [handsFree, press]);

  // Still working: a soft tick every few seconds.
  useEffect(() => {
    if (!handsFree || (state !== "waiting" && state !== "transcribing")) return;
    const timer = window.setInterval(() => {
      playCue("tick");
      setCue("tick");
    }, TICK_MS);
    return () => window.clearInterval(timer);
  }, [handsFree, state]);

  const register = useCallback((sender: Sender) => {
    senders.current.push(sender);
    return () => {
      senders.current = senders.current.filter((item) => item !== sender);
    };
  }, []);

  const readAloud = useCallback(
    (key: string, markdown: string) => {
      stopReading();
      setReading(key);
      void read(markdown)
        .catch((error: unknown) => notify({ kind: "error", title: t("voice.errors.notRead"), text: reasonOf(error) }))
        .finally(() => setReading((now) => (now === key ? null : now)));
    },
    [notify, read, reasonOf, stopReading, t],
  );

  const voice = useMemo<Voice>(
    () => ({
      transcription,
      speech,
      handsFree,
      state,
      cue,
      press: () => void press(),
      showRun: setRunPose,
      runPose,
      stream,
      step,
      failure,
      open,
      close,
      register,
      answered,
      failed,
      reading,
      readAloud,
      stopReading,
    }),
    [transcription, speech, handsFree, state, cue, press, runPose, stream, step, failure, open, close, register, answered, failed, reading, readAloud, stopReading],
  );

  return <VoiceContext.Provider value={voice}>{children}</VoiceContext.Provider>;
}

/** Hands-free mode over the content, while it is on. */
export function HandsFreeOverlay() {
  const voice = useVoice();
  if (!voice?.handsFree) return null;
  return (
    <HandsFree state={voice.state} cue={voice.cue} runPose={voice.runPose} stream={voice.stream} step={voice.step} failure={voice.failure} onPress={voice.press} onClose={voice.close} transcription={voice.transcription} speech={voice.speech} />
  );
}

/** Hands-free mode: one large button that a stray touch does not miss, over the conversation (UX-005). */
function HandsFree(props: {
  state: VoiceState;
  cue: Cue | null;
  runPose: Pose;
  stream: MediaStream | null;
  step: Step | null;
  failure: string | null;
  onPress: () => void;
  onClose: () => void;
  transcription: ModelOption | undefined;
  speech: ModelOption | undefined;
}) {
  const { t } = useTranslation();
  const remote = [props.transcription, props.speech].find((model) => model?.location === "remote");
  const { state } = props;
  const busy = state === "transcribing" || state === "waiting";
  // The sprite acts out what happens: listening, the run's work, reading aloud (UX-013).
  const pose: Pose = state === "listening" ? "listening" : state === "transcribing" ? "thinking" : state === "waiting" ? props.runPose : state === "reading" ? "answering" : state === "failed" ? "error" : "waiting";
  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if (event.key === "Escape") props.onClose();
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [props]);
  return (
    <section aria-label={t("voice.handsFree")} className="absolute inset-0 z-30 flex flex-col gap-3 bg-bg p-4 pb-[max(1rem,env(safe-area-inset-bottom))]">
      <div className="flex items-center gap-2">
        <h2 className="flex flex-1 items-center gap-2 font-semibold">
          <Headphones className="size-5" aria-hidden="true" />
          {t("voice.handsFree")}
        </h2>
        <button type="button" onClick={props.onClose} className="flex items-center gap-1.5 rounded-[10px] border border-line-strong px-3 py-1.5 text-sm font-semibold hover:bg-hover">
          <X className="size-4" aria-hidden="true" />
          {t("voice.leave")}
        </button>
      </div>
      <div className="flex min-h-0 flex-[0.8] items-center justify-center">
        <Sprite pose={pose} className="h-full max-h-[300px] w-auto" />
      </div>
      <div className="relative flex min-h-[200px] flex-1">
      <button
        type="button"
        onClick={props.onPress}
        disabled={busy}
        data-voice-state={state}
        data-voice-cue={props.cue ?? undefined}
        aria-describedby="hands-free-hint"
        className={`flex w-full flex-1 flex-col items-center justify-center gap-4 rounded-[32px] border-4 text-2xl font-bold transition-colors disabled:cursor-wait ${
          state === "listening"
            ? "border-danger bg-danger/10 text-danger"
            : state === "reading"
              ? "border-accent bg-accent-soft text-accent"
              : state === "failed"
                ? "border-danger/60 bg-surface text-fg"
                : "border-line-strong bg-surface text-fg"
        }`}
      >
        {state === "listening" ? (
          // Room for the bars that show the microphone hears, laid over the button.
          <span className="h-16" aria-hidden="true" />
        ) : busy ? (
          <LoaderCircle className="size-16 animate-spin" aria-hidden="true" />
        ) : state === "reading" ? (
          <Volume2 className="size-16" aria-hidden="true" />
        ) : (
          <Mic className="size-16" aria-hidden="true" />
        )}
        <span aria-live="polite">{t(`voice.states.${state}`)}</span>
      </button>
      {/* That the microphone hears, as when dictating; beside the button, so that it has a name of its own. */}
      {state === "listening" && props.stream && (
        <VoiceLevel stream={props.stream} label={t("voice.capturing")} className="pointer-events-none absolute left-[18%] top-1/2 h-16 w-[64%] -translate-y-[calc(100%-0.5rem)] text-danger" />
      )}
      </div>
      <StepLine state={state} step={props.step} failure={props.failure} />
      <p id="hands-free-hint" className="text-center text-sm text-muted">
        {t("voice.hint")} {remote ? t("voice.remote", { connection: remote.connection_name }) : t("voice.local")}
      </p>
    </section>
  );
}

/** Which step the turn is at, in words, with how long it has taken; or which step failed, and why (UX-005). */
function StepLine({ state, step, failure }: { state: VoiceState; step: Step | null; failure: string | null }) {
  const { t } = useTranslation();
  const [now, setNow] = useState(() => Date.now());
  const going = state !== "idle" && state !== "failed" && step !== null;
  useEffect(() => {
    if (!going) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [going]);
  const name = step ? t(`voice.steps.${step.kind}`) : "";
  const part = step?.total !== undefined && step.total > 1 ? t("voice.part", { part: step.part, total: step.total }) : "";
  return (
    <p role="status" className={`min-h-6 text-center text-[15px] font-semibold tabular-nums ${state === "failed" ? "text-danger" : "text-muted"}`}>
      {state === "failed"
        ? `${t("voice.failedStep", { step: name || t("voice.steps.listening") })} ${failure ?? ""}`
        : going
          ? `${name}${part} · ${t("voice.seconds", { count: Math.max(0, Math.floor((now - step.since) / 1000)) })}`
          : ""}
    </p>
  );
}
