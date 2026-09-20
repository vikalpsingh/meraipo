'use client';
import { useEffect } from 'react';
export function revealSection(hash: string) {
  const id = hash.replace(/^#/, '');
  const target = document.getElementById(id);
  if (!target) return;
  let node: HTMLElement | null = target;
  while (node) {
    if (node instanceof HTMLDetailsElement) node.open = true;
    node = node.parentElement;
  }
  target.scrollIntoView({ block: 'start' });
  target.setAttribute('tabindex', '-1');
  target.focus({ preventScroll: true });
}
export function SectionLinks() {
  useEffect(() => {
    const reveal = () => revealSection(window.location.hash);
    if (window.location.hash) reveal();
    window.addEventListener('hashchange', reveal);
    return () => window.removeEventListener('hashchange', reveal);
  }, []);
  return (
    <nav className="guide-nav" aria-label="On this IPO page">
      {[
        ['understand', '1 · Understand'],
        ['apply', '2 · Prepare to apply'],
        ['track', '3 · Track dates'],
        ['financials', 'Financial history ↓'],
      ].map(([id, label]) => (
        <a key={id} href={'#' + id} onClick={() => revealSection('#' + id)}>
          {label}
        </a>
      ))}
    </nav>
  );
}
