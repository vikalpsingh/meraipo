'use client';

import { useEffect, useTransition } from 'react';
import { useRouter } from 'next/navigation';
import {
  defaultTrackerPageSize,
  trackerPageSizeHref,
  trackerPageSizes,
  validTrackerPageSize,
} from '@/lib/tracker-pagination';

export function TrackerPageSize({ query, size }: { query: string; size: number }) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  useEffect(() => {
    if (!validTrackerPageSize(new URLSearchParams(query).get('page_size'))) {
      router.replace(trackerPageSizeHref(query, defaultTrackerPageSize(window.innerWidth)), {
        scroll: false,
      });
    }
  }, [query, router]);

  return (
    <label className="tracker-page-size">
      Rows per page
      <select
        value={size}
        disabled={pending}
        onChange={(event) => {
          const href = trackerPageSizeHref(query, Number(event.target.value));
          startTransition(() => router.push(href, { scroll: false }));
        }}
      >
        {trackerPageSizes.map((count) => (
          <option key={count} value={count}>
            {count}
          </option>
        ))}
      </select>
    </label>
  );
}
