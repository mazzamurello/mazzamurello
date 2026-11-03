import * as Dialog from "@radix-ui/react-dialog";
import * as Menu from "@radix-ui/react-dropdown-menu";
import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router";
import { Ellipsis } from "lucide-react";

import type { Conversation } from "../api/client";
import { deleteConversation, updateConversation, useRefreshConversations } from "../conversations";

const ITEM = "cursor-pointer rounded px-3 py-2 text-sm outline-none data-[highlighted]:bg-hover";

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
        <Menu.Trigger className="grid size-8 flex-none place-items-center rounded-lg text-muted opacity-0 group-hover:opacity-100 hover:bg-hover focus-visible:opacity-100 data-[state=open]:opacity-100 [@media(hover:none)]:opacity-100" aria-label={t("conversationMenu.label", { title })}>
          <Ellipsis className="size-4" aria-hidden="true" />
        </Menu.Trigger>
        <Menu.Portal>
          <Menu.Content className="z-30 min-w-36 rounded-xl border border-line bg-raised p-1 text-fg shadow-soft">
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
            <Menu.Item className={`${ITEM} text-danger`} onSelect={() => setDialog("delete")}>
              {t("conversationMenu.delete")}
            </Menu.Item>
          </Menu.Content>
        </Menu.Portal>
      </Menu.Root>
      <Dialog.Root open={dialog !== null} onOpenChange={(open) => !open && setDialog(null)}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-40 bg-scrim" />
          <Dialog.Content className="rise fixed top-1/2 left-1/2 z-50 w-[min(92vw,26rem)] -translate-x-1/2 -translate-y-1/2 rounded-[20px] bg-raised p-[22px] text-fg shadow-soft">
            {dialog === "rename" ? (
              <form onSubmit={rename} className="space-y-4">
                <Dialog.Title className="text-lg font-semibold">{t("conversationMenu.rename")}</Dialog.Title>
                <Dialog.Description className="sr-only">{t("conversationMenu.renamePrompt")}</Dialog.Description>
                <label className="block">
                  <span className="mb-1 block text-sm">{t("conversationMenu.renamePrompt")}</span>
                  <input name="title" defaultValue={conversation.title} maxLength={200} autoFocus className="h-10 w-full rounded-[10px] border border-line-strong bg-bg px-3 outline-none focus:border-accent" />
                </label>
                <div className="flex justify-end gap-2">
                  <Dialog.Close className="h-[38px] rounded-[10px] border border-line-strong px-4 text-sm font-semibold hover:bg-hover">{t("conversationMenu.cancel")}</Dialog.Close>
                  <button type="submit" className="h-[38px] rounded-[10px] bg-fg px-4 text-sm font-semibold text-bg">
                    {t("conversationMenu.save")}
                  </button>
                </div>
              </form>
            ) : (
              <div className="space-y-4">
                <Dialog.Title className="text-lg font-semibold">{t("conversationMenu.deleteTitle")}</Dialog.Title>
                <Dialog.Description>{t("conversationMenu.deleteBody")}</Dialog.Description>
                <div className="flex justify-end gap-2">
                  <Dialog.Close className="h-[38px] rounded-[10px] border border-line-strong px-4 text-sm font-semibold hover:bg-hover">{t("conversationMenu.cancel")}</Dialog.Close>
                  <button
                    type="button"
                    className="h-[38px] rounded-[10px] bg-danger px-4 text-sm font-semibold text-on-danger"
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
