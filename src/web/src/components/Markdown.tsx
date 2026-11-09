import { type ReactNode, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import ReactMarkdown, { type Components } from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";

import { highlight } from "../highlight";

/**
 * A message in Markdown, with tables, highlighted code and math (UX-002).
 * Raw HTML is never rendered and images are never loaded: a message cannot
 * run scripts or make the browser fetch anything.
 */
export function Markdown({ text }: { text: string }) {
  return (
    <div className="prose-message space-y-3 leading-relaxed break-words">
      <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]} components={COMPONENTS} skipHtml>
        {text}
      </ReactMarkdown>
    </div>
  );
}

const COMPONENTS: Components = {
  a: ({ href, children }) => (
    <a href={href} target="_blank" rel="noopener noreferrer nofollow" className="text-accent underline underline-offset-2">
      {children}
    </a>
  ),
  // No remote resources: an image is shown as its description.
  img: ({ alt }) => <ImageText alt={alt} />,
  table: ({ children }) => (
    <div className="my-1 overflow-x-auto rounded-xl border border-line">
      <table className="w-full border-collapse text-sm [&_td]:border-b [&_td]:border-line [&_td]:px-3 [&_td]:py-2 [&_td]:align-top [&_th]:bg-hover [&_th]:px-3 [&_th]:py-2 [&_th]:text-left [&_th]:text-xs [&_th]:font-semibold [&_th]:tracking-wide [&_th]:text-muted [&_th]:uppercase [&_tr:last-child_td]:border-b-0">
        {children}
      </table>
    </div>
  ),
  ul: ({ children }) => <ul className="list-disc space-y-1 pl-6 marker:text-faint">{children}</ul>,
  ol: ({ children }) => <ol className="list-decimal space-y-1 pl-6 marker:text-faint">{children}</ol>,
  h1: ({ children }) => <h3 className="mt-2 text-xl font-bold tracking-tight">{children}</h3>,
  h2: ({ children }) => <h3 className="mt-2 text-[17px] font-bold tracking-tight">{children}</h3>,
  h3: ({ children }) => <h4 className="mt-1.5 font-bold">{children}</h4>,
  // A task list's box, shown and named rather than offered as a control nobody can use.
  input: ({ type, checked }) => (type === "checkbox" ? <TaskBox done={checked === true} /> : null),
  pre: ({ children }) => <>{children}</>,
  code: ({ className, children }) => {
    const language = /language-([\w-]+)/.exec(className ?? "")?.[1];
    const code = String(children ?? "").replace(/\n$/, "");
    if (language === undefined && !code.includes("\n")) {
      return <code className="rounded-[5px] bg-hover px-[5px] py-px font-mono text-[0.86em]">{children}</code>;
    }
    return <CodeBlock code={code} language={language ?? "text"} />;
  },
};

export function CodeBlock({ code, language }: { code: string; language: string }) {
  const { t } = useTranslation();
  const [highlighted, setHighlighted] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    let current = true;
    // Shiki escapes the code: the HTML it returns holds only the code's text.
    void highlight(code, language)
      .then((html) => current && setHighlighted(html))
      .catch(() => current && setHighlighted(null));
    return () => {
      current = false;
    };
  }, [code, language]);

  let body: ReactNode = <code>{code}</code>;
  if (highlighted !== null) body = <div className="shiki-block" dangerouslySetInnerHTML={{ __html: highlighted }} />;

  return (
    <div className="overflow-hidden rounded-xl border border-line">
      <div className="flex items-center justify-between bg-hover px-3 py-1 font-mono text-xs text-muted">
        <span>{language}</span>
        <button
          type="button"
          className="rounded-md px-2 py-1 font-sans hover:bg-hover hover:text-fg"
          onClick={() => {
            void navigator.clipboard.writeText(code).then(() => {
              setCopied(true);
              setTimeout(() => setCopied(false), 1500);
            });
          }}
        >
          {copied ? t("message.copied") : t("message.copy")}
        </button>
      </div>
      <pre className="overflow-x-auto bg-surface p-3 font-mono text-[13px]">{body}</pre>
    </div>
  );
}

function ImageText({ alt }: { alt: string | undefined }) {
  const { t } = useTranslation();
  return <span className="italic">[{alt || t("message.image")}]</span>;
}

function TaskBox({ done }: { done: boolean }) {
  const { t } = useTranslation();
  return (
    <>
      <span aria-hidden="true" className="mr-1.5 inline-block font-mono text-muted">
        {done ? "☑" : "☐"}
      </span>
      <span className="sr-only">{t(done ? "tasks.status.completed" : "tasks.status.pending")}: </span>
    </>
  );
}
