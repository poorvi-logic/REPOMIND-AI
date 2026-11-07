import { useEffect, useMemo, useRef } from "react";
import { Highlight, themes } from "prism-react-renderer";
import { cx } from "./ui";

interface CodeViewProps {
  code: string;
  startLine?: number;
  highlight?: [number, number] | null;
  scrollToLine?: number | null;
  className?: string;
}

export function CodeView({ code, startLine = 1, highlight = null, scrollToLine = null, className }: CodeViewProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const normalized = useMemo(() => code.replace(/\n$/, ""), [code]);

  useEffect(() => {
    if (!scrollToLine || !containerRef.current) return;
    const target = containerRef.current.querySelector<HTMLElement>(`[data-line="${scrollToLine}"]`);
    target?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [scrollToLine, code]);

  return (
    <div ref={containerRef} className={cx("scrollbar-thin max-h-[70vh] overflow-auto rounded-xl border border-navy-600/70 bg-navy-950/80 font-mono text-[12.5px] leading-6", className)}>
      <Highlight theme={themes.nightOwl} code={normalized} language="python">
        {({ tokens, getTokenProps, className: preClass, style }) => (
          <pre className={cx("m-0 min-w-max py-3", preClass)} style={{ ...style, background: "transparent" }}>
            {tokens.map((line, index) => {
              const lineNumber = startLine + index;
              const active = highlight !== null && highlight !== undefined && lineNumber >= highlight[0] && lineNumber <= highlight[1];
              const focused = scrollToLine === lineNumber;
              return (
                <div
                  key={lineNumber}
                  data-line={lineNumber}
                  className={cx("flex pr-6", active && "bg-accent/12", focused && "bg-accent/20 shadow-[inset_3px_0_0_#8c9bff]")}
                >
                  <span className="sticky left-0 w-14 shrink-0 select-none bg-navy-950/95 pr-4 text-right text-ink-500">{lineNumber}</span>
                  <span className="pl-4">
                    {line.map((token, tokenIndex) => (
                      <span key={tokenIndex} {...getTokenProps({ token })} />
                    ))}
                    {line.length === 0 && " "}
                  </span>
                </div>
              );
            })}
          </pre>
        )}
      </Highlight>
    </div>
  );
}
