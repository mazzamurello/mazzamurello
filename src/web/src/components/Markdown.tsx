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
    <a href={href} target="_blank" rel="noopener noreferrer nofollow" className="text-amber-800 underline dark:text-amber-300">
      {children}
    </a>
  ),
  // No remote resources: an image is shown as its description.
  img: ({ alt }) => <ImageText alt={alt} />,
  table: ({ children }) => (
    <div className="overflow-x-auto">
      <table className="border-collapse text-sm [&_td]:border [&_td]:border-stone-300 [&_td]:px-2 [&_td]:py-1 [&_th]:border [&_th]:border-stone-300 [&_th]:px-2 [&_th]:py-1">
        {children}
      </table>
    </div>
  ),
  ul: ({ children }) => <ul className="list-disc space-y-1 pl-6">{children}</ul>,
  ol: ({ children }) => <ol className="list-decimal space-y-1 pl-6">{children}</ol>,
  h1: ({ children }) => <h3 className="text-xl font-semibold">{children}</h3>,
  h2: ({ children }) => <h3 className="text-lg font-semibold">{children}</h3>,
  h3: ({ children }) => <h4 className="font-semibold">{children}</h4>,
  pre: ({ children }) => <>{children}</>,
  code: ({ className, children }) => {
    const language = /language-([\w-]+)/.exec(className ?? "")?.[1];
    const code = String(children ?? "").replace(/\n$/, "");
    if (language === undefined && !code.includes("\n")) {
      return <code className="rounded bg-stone-200 px-1 py-0.5 text-[0.9em] dark:bg-stone-700">{children}</code>;
    }
    return <CodeBlock code={code} language={language ?? "text"} />;
  },
};

function CodeBlock({ code, language }: { code: string; language: string }) {
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
    <div className="overflow-hidden rounded-lg border border-stone-300 dark:border-stone-600">
      <div className="flex items-center justify-between bg-stone-200 px-3 py-1 text-xs dark:bg-stone-700">
        <span>{language}</span>
        <button
          type="button"
          className="rounded px-2 py-1 hover:bg-stone-300 dark:hover:bg-stone-600"
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
      <pre className="overflow-x-auto bg-white p-3 text-sm dark:bg-stone-900">{body}</pre>
    </div>
  );
}

function ImageText({ alt }: { alt: string | undefined }) {
  const { t } = useTranslation();
  return <span className="italic">[{alt || t("message.image")}]</span>;
}
