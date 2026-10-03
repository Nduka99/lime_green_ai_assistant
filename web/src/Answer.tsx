import type { AnswerView, RecordedAnswer, Source } from "./api";
import { AlertIcon, OpenIcon } from "./Icons";
import { safeLink } from "./links";

const STATUS_LABELS: Record<string, string> = {
  answered: "Answer",
  insufficient_evidence: "Not enough information",
  safety_referral: "Safety referral",
};

/** One verified answer: what it was understood as (on a follow-up), its claims
 * with numbered sources, the fixed notice, and the closest pages on a refusal. */
export function Answer({ recorded }: { recorded: RecordedAnswer }) {
  const { answer, turn, understood_as: understood } = recorded;
  const anchor = (number: number) => `t${turn}-s${number}`;
  if (answer.status === "safety_referral") {
    return <Safety notice={answer.notice} id={`t${turn}-safety`} />;
  }
  return (
    <div className="answer">
      <p className={`status status-${answer.status}`}>{STATUS_LABELS[answer.status]}</p>
      {turn > 1 && understood.length > 0 && (
        <p className="understood">
          <span className="understood-label">Understood as</span>{" "}
          {understood.join(" · ")}
        </p>
      )}
      {answer.claims.length > 0 && (
        <ol className="claims">
          {answer.claims.map((claim, index) => (
            <li key={index}>
              {claim.text}
              {claim.sources.map((number) => (
                <a
                  key={number}
                  className="ref"
                  href={`#${anchor(number)}`}
                  aria-label={`Source ${number}`}
                >
                  {number}
                </a>
              ))}
            </li>
          ))}
        </ol>
      )}
      {answer.notice && <Notice text={answer.notice} />}
      {answer.sources.length > 0 && (
        <Sources sources={answer.sources} anchor={anchor} />
      )}
      {answer.closest_pages.length > 0 && <ClosestPages answer={answer} />}
    </div>
  );
}

function Safety({ notice, id }: { notice: string; id: string }) {
  return (
    <section className="safety" aria-labelledby={id}>
      <h3 className="safety-heading" id={id}>
        <AlertIcon />
        Safety referral
      </h3>
      <Notice text={notice} />
    </section>
  );
}

/** Fixed application text: lines starting "- " are steps, shown as a list. */
export function Notice({ text }: { text: string }) {
  const blocks: (string | string[])[] = [];
  for (const line of text.split("\n")) {
    const last = blocks.at(-1);
    if (line.startsWith("- ") && Array.isArray(last)) last.push(line.slice(2));
    else if (line.startsWith("- ")) blocks.push([line.slice(2)]);
    else blocks.push(line);
  }
  return (
    <div className="notice">
      {blocks.map((block, index) =>
        Array.isArray(block) ? (
          <ul key={index}>
            {block.map((step, item) => (
              <li key={item}>{step}</li>
            ))}
          </ul>
        ) : (
          <p key={index}>{block}</p>
        ),
      )}
    </div>
  );
}

function Sources({
  sources,
  anchor,
}: {
  sources: Source[];
  anchor: (number: number) => string;
}) {
  return (
    <section className="sources" aria-label="Sources">
      <h3 className="section-heading">Sources</h3>
      <ol>
        {sources.map((source) => {
          const page = safeLink(source.url);
          const quoted = safeLink(source.link);
          return (
            <li key={source.number} id={anchor(source.number)}>
              <span className="source-number" aria-hidden="true">
                {source.number}
              </span>
              <div className="source-body">
                <p className="source-title">
                  {page ? <a href={page}>{source.title}</a> : source.title}
                  {source.heading && (
                    <span className="source-heading"> › {source.heading}</span>
                  )}
                </p>
                <blockquote>{source.quote}</blockquote>
                <p className="source-meta">
                  {quoted && (
                    <a href={quoted} target="_blank" rel="noopener noreferrer">
                      <OpenIcon />
                      Open at this quote
                    </a>
                  )}
                  <span>Captured {source.captured}</span>
                </p>
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function ClosestPages({ answer }: { answer: AnswerView }) {
  return (
    <section className="closest" aria-label="Closest pages">
      <h3 className="section-heading">Closest pages</h3>
      <ul>
        {answer.closest_pages.map((page) => {
          const link = safeLink(page.url);
          return (
            <li key={page.url}>
              {link ? <a href={link}>{page.title}</a> : page.title}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
