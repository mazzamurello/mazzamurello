// Code highlighting with Shiki's core and its JavaScript regex engine: no
// WebAssembly, which the Content Security Policy does not allow, and only the
// languages a household's conversations use, each loaded when first needed.
import type { HighlighterCore, LanguageInput } from "shiki/core";

const LANGUAGES: Record<string, () => LanguageInput> = {
  bash: () => import("shiki/dist/langs/bash.mjs"),
  css: () => import("shiki/dist/langs/css.mjs"),
  diff: () => import("shiki/dist/langs/diff.mjs"),
  docker: () => import("shiki/dist/langs/docker.mjs"),
  go: () => import("shiki/dist/langs/go.mjs"),
  html: () => import("shiki/dist/langs/html.mjs"),
  ini: () => import("shiki/dist/langs/ini.mjs"),
  java: () => import("shiki/dist/langs/java.mjs"),
  javascript: () => import("shiki/dist/langs/javascript.mjs"),
  json: () => import("shiki/dist/langs/json.mjs"),
  markdown: () => import("shiki/dist/langs/markdown.mjs"),
  nginx: () => import("shiki/dist/langs/nginx.mjs"),
  python: () => import("shiki/dist/langs/python.mjs"),
  rust: () => import("shiki/dist/langs/rust.mjs"),
  sql: () => import("shiki/dist/langs/sql.mjs"),
  toml: () => import("shiki/dist/langs/toml.mjs"),
  tsx: () => import("shiki/dist/langs/tsx.mjs"),
  typescript: () => import("shiki/dist/langs/typescript.mjs"),
  yaml: () => import("shiki/dist/langs/yaml.mjs"),
};
const ALIASES: Record<string, string> = {
  sh: "bash",
  shell: "bash",
  zsh: "bash",
  console: "bash",
  dockerfile: "docker",
  js: "javascript",
  jsx: "javascript",
  ts: "typescript",
  py: "python",
  yml: "yaml",
  md: "markdown",
  rs: "rust",
  conf: "ini",
};

let highlighter: Promise<HighlighterCore> | null = null;

function core(): Promise<HighlighterCore> {
  highlighter ??= Promise.all([
    import("shiki/core"),
    import("shiki/engine/javascript"),
    import("shiki/dist/themes/github-light.mjs"),
    import("shiki/dist/themes/github-dark.mjs"),
  ]).then(([{ createHighlighterCore }, { createJavaScriptRegexEngine }, light, dark]) =>
    createHighlighterCore({ themes: [light, dark], langs: [], engine: createJavaScriptRegexEngine() }),
  );
  return highlighter;
}

/** The code as highlighted HTML, or `null` for a language not in the list. */
export async function highlight(code: string, language: string): Promise<string | null> {
  const name = ALIASES[language] ?? language;
  const load = LANGUAGES[name];
  if (load === undefined) return null;
  const shiki = await core();
  if (!shiki.getLoadedLanguages().includes(name)) await shiki.loadLanguage(load());
  return shiki.codeToHtml(code, { lang: name, themes: { light: "github-light", dark: "github-dark" }, defaultColor: false });
}
