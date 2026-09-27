'use client';
import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
type Feature = { key: string; label: string; description: string; enabled: boolean };

export function FeatureControls({ csrf }: { csrf: string }) {
  const [items, setItems] = useState<Feature[]>([]);
  const [status, setStatus] = useState('Loading feature controls…');
  const [busy, setBusy] = useState<string | null>(null);
  const router = useRouter();
  useEffect(() => {
    let active = true;
    fetch('/api/v1/admin/features')
      .then(async (response) => {
        if (!response.ok) throw new Error('Could not load feature controls.');
        const data = await response.json();
        if (active) {
          setItems(data.items);
          setStatus('');
        }
      })
      .catch(() => {
        if (active) setStatus('Could not load feature controls. Reload to retry.');
      });
    return () => {
      active = false;
    };
  }, []);
  async function toggle(feature: Feature) {
    setBusy(feature.key);
    setStatus('Saving…');
    try {
      const response = await fetch('/api/v1/admin/features/' + feature.key, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
        body: JSON.stringify({ enabled: !feature.enabled }),
      });
      if (!response.ok) throw new Error('Save failed');
      const saved = await response.json();
      setItems((current) =>
        current.map((item) =>
          item.key === saved.key ? { ...item, enabled: saved.enabled } : item,
        ),
      );
      setStatus(`${feature.label} is now ${saved.enabled ? 'live' : 'hidden'}.`);
      router.refresh();
    } catch {
      setStatus('Could not save. The feature state has not been changed here; reload to verify.');
    } finally {
      setBusy(null);
    }
  }
  return (
    <section className="panel">
      <h2>Feature releases</h2>
      <p>
        Keep unfinished tabs hidden. Enable a feature when it is ready for visitors. New features
        start hidden.
      </p>
      <p role="status">{status}</p>
      {items.map((feature) => (
        <div key={feature.key} className="card">
          <h3>{feature.label}</h3>
          <p>{feature.description}</p>
          <p>
            {feature.enabled ? 'Live — visible to visitors' : 'Hidden — unavailable to visitors'}
          </p>
          <button
            type="button"
            role="switch"
            aria-checked={feature.enabled}
            aria-label={feature.label}
            disabled={busy !== null}
            onClick={() => toggle(feature)}
          >
            {feature.enabled ? 'Hide feature' : 'Enable and make live'}
          </button>
        </div>
      ))}
    </section>
  );
}
