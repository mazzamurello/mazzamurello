import * as Dialog from "@radix-ui/react-dialog";
import * as Menu from "@radix-ui/react-dropdown-menu";
import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router";

import type { Conversation } from "../api/client";
import { deleteConversation, updateConversation, useRefreshConversations } from "../conversations";

const ITEM = "cursor-pointer rounded px-3 py-2 text-sm outline-none data-[highlighted]:bg-stone-200 dark:data-[highlighted]:bg-stone-700";

/** Rename, archive or delete a conversation (API-003). */
export function ConversationMenu({ conversation }: { conversation: Conversation }) {
  const { t } = useTranslation();
  const refresh = useRefreshConversations();
  const navigate = useNavigate();
  const { conversationId } = useParams();
  const [dialog, setDialog] = useState<"rename" | "delete" | null>(null);
  const title = conversation.title || t("shell.untitled");

  async function leaveIfOpen() {
    if (conversationId === conversation.id) await navigate("/");
  }

  async function rename(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const name = String(new FormData(event.currentTarget).get("title") ?? "").trim();
    if (name) await updateConversation(conversation.id, { title: name });
    setDialog(null);
    await refresh();
  }

  return (
    <>
      <Menu.Root>
        <Menu.Trigger className="rounded px-2 py-1 text-stone-700 dark:text-stone-200" aria-label={t("conversationMenu.label", { title })}>
          ⋯
        </Menu.Trigger>
        <Menu.Portal>
          <Menu.Content className="z-30 min-w-36 rounded-lg border border-stone-300 bg-white p-1 shadow-lg dark:border-stone-600 dark:bg-stone-800">
            <Menu.Item className={ITEM} onSelect={() => setDialog("rename")}>
              {t("conversationMenu.rename")}
            </Menu.Item>
            <Menu.Item
              className={ITEM}
              onSelect={async () => {
                await updateConversation(conversation.id, { archived: true });
                await leaveIfOpen();
                await refresh();
              }}
            >
              {t("conversationMenu.archive")}
            </Menu.Item>
            <Menu.Item className={`${ITEM} text-red-800 dark:text-red-300`} onSelect={() => setDialog("delete")}>
              {t("conversationMenu.delete")}
            </Menu.Item>
          </Menu.Content>
        </Menu.Portal>
      </Menu.Root>
      <Dialog.Root open={dialog !== null} onOpenChange={(open) => !open && setDialog(null)}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-40 bg-black/40" />
          <Dialog.Content className="fixed top-1/2 left-1/2 z-50 w-[min(92vw,26rem)] -translate-x-1/2 -translate-y-1/2 rounded-xl bg-white p-5 shadow-xl dark:bg-stone-800">
            {dialog === "rename" ? (
              <form onSubmit={rename} className="space-y-4">
                <Dialog.Title className="text-lg font-semibold">{t("conversationMenu.rename")}</Dialog.Title>
                <Dialog.Description className="sr-only">{t("conversationMenu.renamePrompt")}</Dialog.Description>
                <label className="block">
                  <span className="mb-1 block text-sm">{t("conversationMenu.renamePrompt")}</span>
                  <input name="title" defaultValue={conversation.title} maxLength={200} autoFocus className="w-full rounded-lg border border-stone-400 bg-white px-3 py-2 text-stone-900" />
                </label>
                <div className="flex justify-end gap-2">
                  <Dialog.Close className="rounded-lg px-3 py-2">{t("conversationMenu.cancel")}</Dialog.Close>
                  <button type="submit" className="rounded-lg bg-stone-800 px-3 py-2 text-white">
                    {t("conversationMenu.save")}
                  </button>
                </div>
              </form>
            ) : (
              <div className="space-y-4">
                <Dialog.Title className="text-lg font-semibold">{t("conversationMenu.deleteTitle")}</Dialog.Title>
                <Dialog.Description>{t("conversationMenu.deleteBody")}</Dialog.Description>
                <div className="flex justify-end gap-2">
                  <Dialog.Close className="rounded-lg px-3 py-2">{t("conversationMenu.cancel")}</Dialog.Close>
                  <button
                    type="button"
                    className="rounded-lg bg-red-800 px-3 py-2 text-white"
                    onClick={async () => {
                      await deleteConversation(conversation.id);
                      setDialog(null);
                      await leaveIfOpen();
                      await refresh();
                    }}
                  >
                    {t("conversationMenu.confirmDelete")}
                  </button>
                </div>
              </div>
            )}
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </>
  );
}
