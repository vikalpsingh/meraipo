'use client';

import Link from 'next/link';
import { Search, X } from 'lucide-react';
import { useRef, useState } from 'react';

export function IPOSearch({ query }: { query: string }) {
  const [expanded, setExpanded] = useState(Boolean(query));
  const trigger = useRef<HTMLButtonElement>(null);
  function close() {
    setExpanded(false);
    trigger.current?.focus();
  }
  return (
    <div
      className="compact-search"
      onKeyDown={(event) => {
        if (event.key === 'Escape') close();
      }}
    >
      <button
        ref={trigger}
        type="button"
        className="outline-button search-toggle"
        aria-label="Find an IPO or company"
        title="Find an IPO or company"
        aria-expanded={expanded}
        aria-controls="ipo-search-panel"
        onClick={() => setExpanded(!expanded)}
      >
        <Search size={19} aria-hidden="true" />
      </button>
      {expanded && (
        <form id="ipo-search-panel" className="ipo-search" action="/" role="search">
          <label htmlFor="ipo-search">Find an IPO or company</label>
          <div>
            <input
              id="ipo-search"
              name="q"
              type="search"
              maxLength={120}
              defaultValue={query}
              placeholder="Company name or symbol"
              autoFocus
            />
            <button className="primary-button">Search</button>
            <button
              type="button"
              className="search-dismiss"
              aria-label="Close search"
              onClick={close}
            >
              <X size={18} aria-hidden="true" />
            </button>
          </div>
          {query && (
            <Link href="/" className="text-link">
              Clear search
            </Link>
          )}
        </form>
      )}
    </div>
  );
}
