// What an answer sounds like when it is read aloud (UX-005, ADR-0088).
import { describe, expect, it } from "vitest";

import { pieces, speakable } from "../../../src/web/src/speech";

const NAMES = { code: "There is a code block.", table: "There is a table.", image: "There is an image.", diagram: "There is a diagram." };

describe("speakable", () => {
  it("keeps prose, without its Markdown", () => {
    expect(speakable("# Plan\n\nFirst **buy** the _tickets_, then `pack`.", NAMES)).toBe("Plan\n\nFirst buy the tickets, then pack.");
  });

  it("names code, tables, images and diagrams instead of reading them", () => {
    const text = speakable(
      "Run this:\n\n```python\nprint('x')\n```\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n![chart](chart.png)\n\n```mermaid\ngraph TD; A-->B\n```\n\nDone.",
      NAMES,
    );
    expect(text).toBe("Run this:\n\nThere is a code block.\n\nThere is a table.\n\nThere is an image.\n\nThere is a diagram.\n\nDone.");
  });

  it("says a link by its text", () => {
    expect(speakable("See [the docs](https://example.com/very/long/path) or https://example.com.", NAMES)).toBe("See the docs or example.com.");
  });

  it("reads list items as sentences", () => {
    expect(speakable("Steps:\n\n- one\n- two\n1. three", NAMES)).toBe("Steps:\n\none\ntwo\nthree");
  });
});

describe("pieces", () => {
  it("keeps a short text whole", () => {
    expect(pieces("Hello. World.", 4000)).toEqual(["Hello. World."]);
  });

  it("splits at paragraphs, then sentences, within the limit", () => {
    const sentence = "This is a sentence of words. ";
    const paragraph = sentence.repeat(10).trim();
    const result = pieces(`${paragraph}\n\n${paragraph}`, 400);
    expect(result.every((piece) => piece.length <= 400)).toBe(true);
    expect(result.join(" ").replace(/\s+/g, " ")).toBe(`${paragraph} ${paragraph}`);
    expect(result.every((piece) => piece.endsWith("."))).toBe(true);
  });

  it("cuts a sentence longer than the limit at a space", () => {
    const result = pieces("word ".repeat(30).trim(), 50);
    expect(result.every((piece) => piece.length <= 50 && !piece.startsWith(" "))).toBe(true);
  });

  it("makes the first piece short, since the reading waits for it", () => {
    const sentence = "This is a sentence of words. ";
    const result = pieces(sentence.repeat(40).trim(), 4000, 100);
    expect((result[0] ?? "").length).toBeLessThanOrEqual(100);
    expect(result.length).toBe(2);
    expect(result.join(" ").replace(/\s+/g, " ")).toBe(sentence.repeat(40).trim());
  });

  it("drops empty text", () => {
    expect(pieces("  \n\n ", 4000)).toEqual([]);
  });
});
