'use client';
import { usePathname } from 'next/navigation';

/** Scope public styling away from all administrator routes, including client navigation. */
export function PublicSurface({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  return (
    <div className={path.startsWith('/meraadmin') ? undefined : 'public-surface'}>{children}</div>
  );
}
