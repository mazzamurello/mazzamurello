import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router";

import { createConversation, useRefreshConversations } from "../conversations";
import { Composer } from "./Composer";

/** A new chat: the conversation is created with its first message. */
export function Welcome() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const refresh = useRefreshConversations();

  async function start(text: string) {
    const conversation = await createConversation();
    await refresh();
    await navigate(`/c/${conversation.id}`, { state: { firstMessage: text } });
  }

  return (
    <div className="flex flex-1 flex-col justify-center">
      <div className="mx-auto w-full max-w-3xl px-4 text-center">
        <h1 className="text-3xl font-semibold">{t("welcome.title")}</h1>
        <p className="mt-2 text-stone-700 dark:text-stone-300">{t("welcome.hint")}</p>
      </div>
      <Composer onSend={(text) => void start(text)} running={false} />
    </div>
  );
}
