/**
 * A tiny syntax highlighter for the generated Python and TypeScript suites: comments,
 * strings, keywords, numbers and decorators. Good enough for code we generate ourselves,
 * and far lighter than shipping a full grammar.
 */
export type Lang = "python" | "typescript";
export type TokenKind = "k" | "s" | "c" | "n" | "d" | null;
export interface Token {
  kind: TokenKind;
  text: string;
}

const KEYWORDS: Record<Lang, Set<string>> = {
  python: new Set(
    "and as assert async await break class continue def del elif else except False finally for from global if import in is lambda None nonlocal not or pass raise return True try while with yield".split(
      " ",
    ),
  ),
  typescript: new Set(
    "as async await break case catch class const continue default do else export extends false finally for from function if import in instanceof let new null of return switch this throw true try type typeof undefined var void while".split(
      " ",
    ),
  ),
};

const QUOTE: Record<Lang, RegExp> = {
  python: /^[rRbBfFuU]{0,2}("""|'''|"|')/,
  typescript: /^("|'|`)/,
};

type Mode = { in: "code" } | { in: "string"; close: string } | { in: "comment" };

/** Split source into lines of tokens, carrying multi-line strings and comments across lines. */
export function highlight(source: string, lang: Lang): Token[][] {
  const lines: Token[][] = [];
  let mode: Mode = { in: "code" };
  for (const line of source.replace(/\r\n/g, "\n").split("\n")) {
    const out: Token[] = [];
    const push = (kind: TokenKind, text: string) => {
      if (!text) return;
      const last = out[out.length - 1];
      if (last && last.kind === kind) last.text += text;
      else out.push({ kind, text });
    };
    let i = 0;
    while (i < line.length) {
      if (mode.in === "string") {
        const end = findClose(line, i, mode.close);
        if (end === -1) {
          push("s", line.slice(i));
          i = line.length;
        } else {
          push("s", line.slice(i, end + mode.close.length));
          i = end + mode.close.length;
          mode = { in: "code" };
        }
        continue;
      }
      if (mode.in === "comment") {
        const end = line.indexOf("*/", i);
        if (end === -1) {
          push("c", line.slice(i));
          i = line.length;
        } else {
          push("c", line.slice(i, end + 2));
          i = end + 2;
          mode = { in: "code" };
        }
        continue;
      }
      const rest = line.slice(i);
      const ch = line[i];
      if ((lang === "python" && ch === "#") || (lang === "typescript" && rest.startsWith("//"))) {
        push("c", rest);
        break;
      }
      if (lang === "typescript" && rest.startsWith("/*")) {
        mode = { in: "comment" };
        push("c", "/*");
        i += 2;
        continue;
      }
      const quote = QUOTE[lang].exec(rest);
      // A string prefix (f"", rb'') only counts at a word boundary, not as the tail of a name.
      if (quote && (quote[0].length === quote[1].length || !/\w/.test(line[i - 1] ?? ""))) {
        const open = quote[0];
        const close = quote[1];
        push("s", open);
        i += open.length;
        // Single-quoted strings never span lines; template and triple-quoted ones can.
        mode = { in: "string", close };
        if (close.length === 1 && close !== "`") {
          const end = findClose(line, i, close);
          push("s", end === -1 ? line.slice(i) : line.slice(i, end + 1));
          i = end === -1 ? line.length : end + 1;
          mode = { in: "code" };
        }
        continue;
      }
      if (ch === "@" && lang === "python" && /^@[\w.]+/.test(rest) && line.slice(0, i).trim() === "") {
        const m = /^@[\w.]+/.exec(rest)!;
        push("d", m[0]);
        i += m[0].length;
        continue;
      }
      const word = /^[A-Za-z_$][\w$]*/.exec(rest);
      if (word) {
        push(KEYWORDS[lang].has(word[0]) ? "k" : null, word[0]);
        i += word[0].length;
        continue;
      }
      const num = /^\d[\d_.]*/.exec(rest);
      if (num && !/\w/.test(line[i - 1] ?? "")) {
        push("n", num[0]);
        i += num[0].length;
        continue;
      }
      push(null, ch);
      i++;
    }
    lines.push(out);
  }
  return lines;
}

function findClose(line: string, from: number, close: string): number {
  for (let i = from; i < line.length; i++) {
    if (line[i] === "\\") {
      i++;
      continue;
    }
    if (line.startsWith(close, i)) return i;
  }
  return -1;
}
