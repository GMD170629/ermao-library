'use client';

import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

export function ReleaseMarkdown({ markdown }: { markdown: string }) {
  return (
    <div data-i18n-skip className="space-y-3 text-sm leading-7 text-[#58534D] [&_a]:font-medium [&_a]:text-[#D94327] [&_a]:underline [&_h2]:pt-1 [&_h2]:text-base [&_h2]:font-semibold [&_h2]:text-[#2A2825] [&_li]:ml-5 [&_li]:list-disc [&_ol_li]:list-decimal [&_p]:leading-7">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        skipHtml
        components={{
          a: ({ children, href }) => (
            <a href={href} target="_blank" rel="noreferrer">
              {children}
            </a>
          ),
          img: ({ alt }) => <span>{alt ?? ''}</span>
        }}
      >
        {markdown}
      </ReactMarkdown>
    </div>
  );
}
