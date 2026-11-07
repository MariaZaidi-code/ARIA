import type { ReactNode } from "react";

/**
 * Minimal, safe Markdown renderer for grounded answers and excerpts.
 * Supports paragraphs, "-"/"*"/"•" and numbered lists, **bold**, and pipe
 * tables. Everything is rendered as React text nodes (never innerHTML), so
 * document content cannot inject markup. Empty list items are dropped and
 * stray emphasis markers are removed instead of being shown literally.
 */

type Block =
  | { kind: "p"; text: string }
  | { kind: "ul" | "ol"; items: string[] }
  | { kind: "table"; header: string[]; rows: string[][] };

const BULLET_RE = /^\s*(?:[-*•‣◦▪])\s+(.*)$/;
const ORDERED_RE = /^\s*\d+[.)]\s+(.*)$/;
const EMPTY_ITEM_RE = /^\s*(?:[-*•‣◦▪]|\d+[.)])\s*$/;
const SEPARATOR_RE = /^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?$/;

function splitRow(line: string) {
  let body = line.trim();
  if (body.startsWith("|")) body = body.slice(1);
  if (body.endsWith("|")) body = body.slice(0, -1);
  return body.split(/(?<!\\)\|/).map((cell) => cell.replace(/\\\|/g, "|").trim());
}

export function parseBlocks(source: string): Block[] {
  const lines = String(source || "").replace(/\r\n/g, "\n").split("\n");
  const blocks: Block[] = [];
  let paragraph: string[] = [];
  const flush = () => {
    if (paragraph.length) blocks.push({ kind: "p", text: paragraph.join(" ") });
    paragraph = [];
  };
  for (let index = 0; index < lines.length; index += 1) {
    const raw = lines[index];
    const line = raw.replace(/^\s{0,3}#{1,6}\s+/, "");
    if (!line.trim() || EMPTY_ITEM_RE.test(line)) {
      flush();
      continue;
    }
    if (line.includes("|") && SEPARATOR_RE.test((lines[index + 1] || "").trim())) {
      flush();
      const header = splitRow(line);
      const rows: string[][] = [];
      index += 2;
      while (index < lines.length && lines[index].includes("|") && lines[index].trim()) {
        const cells = splitRow(lines[index]);
        rows.push(header.map((_, column) => cells[column] ?? ""));
        index += 1;
      }
      index -= 1;
      blocks.push({ kind: "table", header, rows });
      continue;
    }
    const bullet = BULLET_RE.exec(line);
    const ordered = bullet ? null : ORDERED_RE.exec(line);
    if (bullet || ordered) {
      flush();
      const kind = bullet ? "ul" : "ol";
      const text = (bullet || ordered)![1].trim();
      const last = blocks[blocks.length - 1];
      if (last && last.kind === kind) last.items.push(text);
      else blocks.push({ kind, items: [text] });
      continue;
    }
    paragraph.push(line.trim());
  }
  flush();
  return blocks;
}

/** Inline formatting: **bold** spans; any leftover "**" or "__" markers are dropped. */
export function renderInline(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  const pattern = /\*\*(.+?)\*\*/g;
  let last = 0;
  let match: RegExpExecArray | null;
  const plain = (value: string) => value.replace(/\*\*/g, "").replace(/(^|\s)\*(?=\S)/g, "$1").replace(/`([^`]+)`/g, "$1");
  while ((match = pattern.exec(text))) {
    if (match.index > last) out.push(plain(text.slice(last, match.index)));
    out.push(<strong key={`b${match.index}`}>{plain(match[1])}</strong>);
    last = match.index + match[0].length;
  }
  if (last < text.length) out.push(plain(text.slice(last)));
  return out;
}

export function DocumentAnswer({ text, className = "" }: { text: string; className?: string }) {
  const blocks = parseBlocks(text);
  return (
    <div className={`doc-answer-markdown ${className}`}>
      {blocks.map((block, index) => {
        if (block.kind === "p") return <p key={index}>{renderInline(block.text)}</p>;
        if (block.kind === "table") {
          return (
            <div className="doc-answer-table-wrap" key={index}>
              <table>
                <thead>
                  <tr>{block.header.map((cell, column) => <th key={column} scope="col">{renderInline(cell)}</th>)}</tr>
                </thead>
                <tbody>
                  {block.rows.map((row, rowIndex) => (
                    <tr key={rowIndex}>{row.map((cell, column) => <td key={column}>{renderInline(cell)}</td>)}</tr>
                  ))}
                </tbody>
              </table>
            </div>
          );
        }
        const List = block.kind;
        return (
          <List key={index}>
            {block.items.map((item, itemIndex) => <li key={itemIndex}>{renderInline(item)}</li>)}
          </List>
        );
      })}
    </div>
  );
}
