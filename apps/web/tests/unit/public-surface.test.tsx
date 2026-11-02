import { render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { PublicSurface } from '@/components/public-surface';
const route = vi.hoisted(() => ({ path: '/' }));
vi.mock('next/navigation', () => ({ usePathname: () => route.path }));
it('keeps public styling off administrator routes after navigation', () => {
  const view = render(<PublicSurface><span>Page content</span></PublicSurface>);
  for (const path of ['/', '/tracker', '/ipo/example', '/company/example', '/ipo-status', '/email-alerts', '/privacy', '/feedback', '/meraadmin', '/meraadmin/settings']) {
    route.path = path;
    view.rerender(<PublicSurface><span>Page content</span></PublicSurface>);
    expect(screen.getByText('Page content').parentElement?.classList.contains('public-surface')).toBe(!path.startsWith('/meraadmin'));
  }
});
