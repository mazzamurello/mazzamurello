// The assistant's questions to the user, and its task list (AGT-015, UX-009, ADR-0083).
import { Check, ChevronLeft, ChevronRight, Circle, CircleDot, MessageCircleQuestion, X } from "lucide-react";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import type { Interrupt, PlanStep, Question } from "../api/client";
import type { ResumeEntry } from "../api/stream";

const BUTTON = "inline-flex h-[38px] items-center justify-center gap-2 rounded-[10px] border border-line-strong bg-surface px-4 text-sm font-semibold hover:bg-hover disabled:opacity-50";
const ARROW = "grid size-8 place-items-center rounded-lg hover:bg-hover hover:text-fg disabled:opacity-40";
const PRIMARY = "inline-flex h-[38px] items-center justify-center gap-2 rounded-[10px] bg-fg px-4 text-sm font-semibold text-bg disabled:opacity-50";

interface Choice {
  selected: string[];
  ownWords: string;
}

function questionsOf(interrupt: Interrupt): Question[] {
  return interrupt.metadata?.questions ?? [];
}

/** One question: its choices, and a field for the user's own words instead. */
function QuestionField({ question, choice, onChange }: { question: Question; choice: Choice; onChange: (choice: Choice) => void }) {
  const { t } = useTranslation();
  const name = useId();
  const own = useId();
  function toggle(label: string, on: boolean) {
    const selected = question.multi_select ? (on ? [...choice.selected, label] : choice.selected.filter((item) => item !== label)) : [label];
    onChange({ selected, ownWords: "" });
  }
  return (
    <fieldset className="flex flex-col gap-1.5">
      <legend className="mb-1.5 text-[15px] font-semibold text-pretty">{question.question}</legend>
      {question.options.map((option) => (
        <label key={option.label} className="flex cursor-pointer items-start gap-2.5 rounded-[10px] border border-line px-3 py-1.5 hover:bg-hover has-checked:border-fg">
          <input
            type={question.multi_select ? "checkbox" : "radio"}
            name={name}
            checked={choice.selected.includes(option.label)}
            onChange={(event) => toggle(option.label, event.target.checked)}
            className="mt-1 accent-fg"
          />
          <span className="flex flex-col">
            <span className="text-sm font-semibold">{option.label}</span>
            {option.description && <span className="text-[13px] text-muted">{option.description}</span>}
          </span>
        </label>
      ))}
      <label htmlFor={own} className="sr-only">
        {t("questions.ownWords")}
      </label>
      <input
        id={own}
        value={choice.ownWords}
        maxLength={2000}
        placeholder={t("questions.ownWords")}
        onChange={(event) => onChange({ selected: [], ownWords: event.target.value })}
        className="h-10 rounded-[10px] border border-line-strong bg-bg px-3 text-sm outline-none focus:border-accent"
      />
    </fieldset>
  );
}

/** The assistant's questions, in place of the message box until the user answers or skips them: one at a time. */
export function QuestionCard({ interrupts, onAnswer }: { interrupts: Interrupt[]; onAnswer: (resume: ResumeEntry[]) => void }) {
  const { t } = useTranslation();
  const heading = useId();
  const [choices, setChoices] = useState<Record<string, Choice>>({});
  const [index, setIndex] = useState(0);
  const key = (interrupt: Interrupt, question: Question) => `${interrupt.id}\u0000${question.header}`;
  const choiceOf = (interrupt: Interrupt, question: Question) => choices[key(interrupt, question)] ?? { selected: [], ownWords: "" };
  const all = interrupts.flatMap((interrupt) => questionsOf(interrupt).map((question) => ({ interrupt, question })));
  const current = all[Math.min(index, all.length - 1)];
  const isAnswered = (interrupt: Interrupt, question: Question) => {
    const choice = choiceOf(interrupt, question);
    return choice.selected.length > 0 || choice.ownWords.trim() !== "";
  };
  const answered = all.every(({ interrupt, question }) => isAnswered(interrupt, question));
  const last = index >= all.length - 1;

  // A choice stays on its question: the user moves on with Next or the arrows (ADR-0083).
  function choose(interrupt: Interrupt, question: Question, choice: Choice) {
    setChoices((chosen) => ({ ...chosen, [key(interrupt, question)]: choice }));
  }

  function answer() {
    onAnswer(
      interrupts.map((interrupt) => ({
        interruptId: interrupt.id,
        status: "resolved",
        payload: {
          answers: questionsOf(interrupt).map((question) => {
            const choice = choiceOf(interrupt, question);
            return choice.ownWords.trim() !== "" ? { header: question.header, custom_answer: choice.ownWords.trim() } : { header: question.header, selected: choice.selected };
          }),
        },
      })),
    );
  }

  return (
    <section aria-labelledby={heading} className="flex max-h-[min(60dvh,34rem)] flex-col rounded-[20px] border border-line-strong bg-surface shadow-soft">
      <div className="flex flex-none items-center gap-2 px-4 pt-3.5 pb-2">
        <h2 id={heading} className="flex flex-1 items-center gap-2 text-sm font-bold text-muted">
          <MessageCircleQuestion className="size-4" aria-hidden="true" />
          {t("questions.title")}
        </h2>
        {all.length > 1 && (
          <div className="flex items-center gap-1 text-[13px] text-muted tabular-nums">
            <button type="button" className={ARROW} disabled={index === 0} onClick={() => setIndex(index - 1)} aria-label={t("questions.previous")}>
              <ChevronLeft className="size-4" aria-hidden="true" />
            </button>
            <span aria-live="polite">{t("questions.counter", { number: index + 1, total: all.length })}</span>
            <button type="button" className={ARROW} disabled={index >= all.length - 1} onClick={() => setIndex(index + 1)} aria-label={t("questions.next")}>
              <ChevronRight className="size-4" aria-hidden="true" />
            </button>
          </div>
        )}
      </div>
      {current && (
        <div className="min-h-0 overflow-y-auto px-4 pb-2">
          <QuestionField
            key={key(current.interrupt, current.question)}
            question={current.question}
            choice={choiceOf(current.interrupt, current.question)}
            onChange={(choice) => choose(current.interrupt, current.question, choice)}
          />
        </div>
      )}
      <div className="flex flex-none justify-end gap-2 border-t border-line px-4 py-3">
        <button type="button" className={BUTTON} onClick={() => onAnswer(interrupts.map((interrupt) => ({ interruptId: interrupt.id, status: "cancelled" })))}>
          {t("questions.skip")}
        </button>
        {/* Next until the last question, then Answer (ADR-0083). */}
        {last ? (
          <button type="button" className={PRIMARY} disabled={!answered} onClick={answer}>
            {t("questions.answer")}
          </button>
        ) : (
          <button type="button" className={PRIMARY} disabled={!current || !isAnswered(current.interrupt, current.question)} onClick={() => setIndex(index + 1)}>
            {t("questions.nextButton")}
          </button>
        )}
      </div>
    </section>
  );
}

const STATUS_ICONS = {
  completed: Check,
  in_progress: CircleDot,
  pending: Circle,
  cancelled: X,
  blocked: Circle,
} as const;

/** The task list, as a checklist: what is done, what goes on, what is left (UX-009). */
export function TaskList({ steps }: { steps: PlanStep[] }) {
  const { t } = useTranslation();
  if (steps.length === 0) return null;
  const done = steps.filter((step) => step.status === "completed").length;
  return (
    <div className="mb-2 rounded-2xl border border-line bg-surface px-3.5 py-2.5">
      <p className="mb-1.5 text-xs font-semibold text-muted">{t("tasks.progress", { done, total: steps.length })}</p>
      <ul aria-label={t("tasks.title")} className="flex max-h-40 flex-col gap-1 overflow-y-auto">
        {steps.map((step) => {
          const Icon = STATUS_ICONS[step.status];
          const going = step.status === "in_progress";
          return (
            <li key={step.id} className={`flex items-start gap-2 text-sm ${step.status === "completed" || step.status === "cancelled" ? "text-muted" : ""}`}>
              <Icon className={`mt-0.5 size-4 flex-none ${going ? "text-accent" : ""}`} aria-hidden="true" />
              <span className="sr-only">{t(`tasks.status.${step.status}`)}: </span>
              <span className={`${step.status === "cancelled" ? "line-through" : ""} ${going ? "live-text font-semibold" : ""}`}>{going ? (step.active_form ?? step.content) : step.content}</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
