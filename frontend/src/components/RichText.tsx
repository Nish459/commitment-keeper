import { Fragment, type ReactNode } from "react";

const INLINE = /\*\*([^*]+)\*\*|\[(\d+)\]/g;

/** Bold and [n] citations only. Everything else stays literal text, so nothing is injected as HTML. */
function inline(text: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  let last = 0;
  for (const match of text.matchAll(INLINE)) {
    const index = match.index ?? 0;
    if (index > last) nodes.push(text.slice(last, index));
    if (match[1] !== undefined) {
      nodes.push(<strong key={index}>{match[1]}</strong>);
    } else {
      nodes.push(
        <sup className="cite" key={index}>
          <a href={`#src-${match[2]}`} aria-label={`Source ${match[2]}`}>
            {match[2]}
          </a>
        </sup>,
      );
    }
    last = index + match[0].length;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}

function blocks(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  let list: string[] | null = null;
  let paragraph: string[] = [];

  const flushParagraph = () => {
    if (!paragraph.length) return;
    const lines = paragraph;
    out.push(
      <p key={out.length}>
        {lines.map((line, i) => (
          <Fragment key={i}>
            {i > 0 && <br />}
            {inline(line)}
          </Fragment>
        ))}
      </p>,
    );
    paragraph = [];
  };
  const flushList = () => {
    if (!list) return;
    const items = list;
    out.push(
      <ul key={out.length}>
        {items.map((item, i) => (
          <li key={i}>{inline(item)}</li>
        ))}
      </ul>,
    );
    list = null;
  };

  for (const raw of text.split("\n")) {
    const line = raw.trim();
    const bullet = /^[-*]\s+(.*)/.exec(line);
    if (!line) {
      flushParagraph();
      flushList();
    } else if (bullet) {
      flushParagraph();
      (list ??= []).push(bullet[1] ?? "");
    } else {
      flushList();
      paragraph.push(line);
    }
  }
  flushParagraph();
  flushList();
  return out;
}

function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

/** Splits the "Sources:" block the server appends; renders the body plus a numbered source list. */
export function DraftBody({ body }: { body: string }) {
  const [main = "", sourceBlock = ""] = body.split(/\n\s*Sources:\s*\n/);
  const sources = [...sourceBlock.matchAll(/^\[(\d+)\]\s+(\S+)/gm)].map((m) => ({
    n: m[1] ?? "",
    url: m[2] ?? "",
  }));
  return (
    <>
      <div className="draft-text">{blocks(main.trim())}</div>
      {sources.length > 0 && (
        <ol className="sources" aria-label="Sources">
          {sources.map(({ n, url }) => (
            <li key={n} id={`src-${n}`}>
              <span className="src-n">{n}</span>
              <a href={url} target="_blank" rel="noopener noreferrer" title={url}>
                {hostOf(url)}
              </a>
            </li>
          ))}
        </ol>
      )}
    </>
  );
}
