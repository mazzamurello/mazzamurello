import { RefreshCw } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router";

import type { ModelChoice, User } from "../api/client";
import { createConversation, useRefreshConversations } from "../conversations";
import { useModels } from "../models";
import { Composer } from "./Composer";
import { Sprite } from "./Sprite";

interface Quote {
  text: string;
  author: string;
  work: string;
}


/** A new chat: the sprite greets with a quote, and the conversation is created with its first message (UX-012). */
export function Welcome({ me }: { me: User }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const refresh = useRefreshConversations();
  const models = useModels();
  const [chosen, setChosen] = useState<ModelChoice | null>(null);
  const quotes = t("quotes", { returnObjects: true }) as Quote[];
  const [index, setIndex] = useState(() => Math.floor(Math.random() * quotes.length));
  const quote = quotes[index % quotes.length];
  const model = chosen ?? models.data?.default ?? null;
  const hour = new Date().getHours();
  const name = me.display_name;
  const greeting = hour < 12 ? t("welcome.morning", { name }) : hour < 18 ? t("welcome.afternoon", { name }) : t("welcome.evening", { name });

  async function start(text: string) {
    const conversation = await createConversation(chosen ?? undefined);
    await refresh();
    await navigate(`/c/${conversation.id}`, { state: { firstMessage: text } });
  }

  function another() {
    if (quotes.length < 2) return;
    let next = index;
    while (next === index) next = Math.floor(Math.random() * quotes.length);
    setIndex(next);
  }

  return (
    <div className="flex flex-1 overflow-y-auto">
      <div className="m-auto flex w-full max-w-[760px] flex-col gap-7 px-4 pt-4 pb-12">
        <div className="flex flex-col items-center justify-center gap-3.5 sm:flex-row sm:gap-2">
          <Sprite pose="greeting" className="h-[124px] w-[108px] flex-none sm:h-[152px] sm:w-[132px]" />
          {quote && (
            <figure className="relative m-0 max-w-[460px] rounded-[22px] border border-line bg-surface px-[22px] pt-[18px] pb-4 shadow-soft">
              <p className="mb-2 text-xl font-bold tracking-tight text-balance">{greeting}</p>
              <blockquote className="m-0 font-serif text-[19px] leading-[1.45] italic text-pretty">“{quote.text}”</blockquote>
              <figcaption className="mt-2 flex items-center gap-1.5 text-[13.5px] text-muted">
                <span className="flex-1">
                  {quote.author}
                  {quote.work && (
                    <>
                      , <cite>{quote.work}</cite>
                    </>
                  )}
                </span>
                <button type="button" onClick={another} className="grid size-8 place-items-center rounded-lg hover:bg-hover hover:text-fg" aria-label={t("welcome.anotherQuote")} title={t("welcome.anotherQuote")}>
                  <RefreshCw className="size-4" aria-hidden="true" />
                </button>
              </figcaption>
            </figure>
          )}
        </div>
        <Composer onSend={(text) => void start(text)} running={false} model={model} onModel={setChosen} placeholder={t("welcome.placeholder")} />
      </div>
    </div>
  );
}
