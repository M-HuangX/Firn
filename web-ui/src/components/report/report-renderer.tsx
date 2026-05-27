"use client";

import { memo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Components } from "react-markdown";

// ─── Rehype plugin: inject data-source-line on block elements ─────────────────

function rehypeSourceLines() {
  return (tree: { type: string; children: HastNode[] }) => {
    visitBlock(tree);
  };
}

interface HastNode {
  type: string;
  tagName?: string;
  properties?: Record<string, unknown>;
  position?: { start: { line: number } };
  children?: HastNode[];
}

const BLOCK_TAGS = new Set([
  "p", "h1", "h2", "h3", "h4", "h5", "h6",
  "li", "tr", "blockquote", "pre", "table",
]);

function visitBlock(node: HastNode) {
  if (
    node.type === "element" &&
    node.tagName &&
    BLOCK_TAGS.has(node.tagName) &&
    node.position?.start.line
  ) {
    node.properties = node.properties || {};
    node.properties["data-source-line"] = node.position.start.line;
  }
  if (node.children) {
    for (const child of node.children) {
      visitBlock(child);
    }
  }
}

// ─── Custom components for dark theme ─────────────────────────────────────────

const components: Components = {
  h1: ({ children, ...props }) => (
    <h1 className="text-2xl font-bold text-text-primary mt-8 mb-4 pb-2 border-b border-border" {...props}>
      {children}
    </h1>
  ),
  h2: ({ children, ...props }) => (
    <h2 className="text-xl font-semibold text-text-primary mt-6 mb-3" {...props}>
      {children}
    </h2>
  ),
  h3: ({ children, ...props }) => (
    <h3 className="text-lg font-medium text-text-primary mt-5 mb-2" {...props}>
      {children}
    </h3>
  ),
  h4: ({ children, ...props }) => (
    <h4 className="text-base font-medium text-text-secondary mt-4 mb-2" {...props}>
      {children}
    </h4>
  ),
  p: ({ children, ...props }) => (
    <p className="text-text-primary leading-7 mb-4" {...props}>
      {children}
    </p>
  ),
  ul: ({ children, ...props }) => (
    <ul className="list-disc list-outside ml-6 mb-4 space-y-1 text-text-primary" {...props}>
      {children}
    </ul>
  ),
  ol: ({ children, ...props }) => (
    <ol className="list-decimal list-outside ml-6 mb-4 space-y-1 text-text-primary" {...props}>
      {children}
    </ol>
  ),
  li: ({ children, ...props }) => (
    <li className="text-text-primary leading-7" {...props}>
      {children}
    </li>
  ),
  blockquote: ({ children, ...props }) => (
    <blockquote className="border-l-4 border-accent/40 pl-4 my-4 text-text-secondary italic" {...props}>
      {children}
    </blockquote>
  ),
  code: ({ className, children, ...props }) => {
    const isBlock = className?.includes("language-");
    if (isBlock) {
      return (
        <code className={`${className} block`} {...props}>
          {children}
        </code>
      );
    }
    return (
      <code className="bg-surface px-1.5 py-0.5 rounded text-sm font-mono text-accent" {...props}>
        {children}
      </code>
    );
  },
  pre: ({ children, ...props }) => (
    <pre className="bg-background border border-border rounded-lg p-4 overflow-x-auto mb-4 text-sm font-mono" {...props}>
      {children}
    </pre>
  ),
  table: ({ children, ...props }) => (
    <div className="overflow-x-auto mb-4">
      <table className="w-full text-sm border-collapse" {...props}>
        {children}
      </table>
    </div>
  ),
  thead: ({ children, ...props }) => (
    <thead className="border-b border-border" {...props}>
      {children}
    </thead>
  ),
  th: ({ children, ...props }) => (
    <th className="text-left px-3 py-2 font-medium text-text-secondary" {...props}>
      {children}
    </th>
  ),
  td: ({ children, ...props }) => (
    <td className="px-3 py-2 text-text-primary border-t border-border/50" {...props}>
      {children}
    </td>
  ),
  a: ({ children, href, ...props }) => (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="text-interactive hover:underline"
      {...props}
    >
      {children}
    </a>
  ),
  hr: (props) => <hr className="border-border my-6" {...props} />,
  strong: ({ children, ...props }) => (
    <strong className="font-semibold text-text-primary" {...props}>
      {children}
    </strong>
  ),
  em: ({ children, ...props }) => (
    <em className="italic text-text-secondary" {...props}>
      {children}
    </em>
  ),
};

// ─── Main component ───────────────────────────────────────────────────────────

interface ReportRendererProps {
  markdown: string;
  className?: string;
}

export const ReportRenderer = memo(function ReportRenderer({
  markdown,
  className = "",
}: ReportRendererProps) {
  return (
    <div className={`report-content ${className}`} data-testid="report-content">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeSourceLines]}
        components={components}
      >
        {markdown}
      </ReactMarkdown>
    </div>
  );
});
