'use client';

import { useEffect, useRef, useState, type ReactNode } from 'react';

type Stage = { id: string; title: string; count: number; content: ReactNode };

export function IPOStageTabs({ stages }: { stages: Stage[] }) {
  const [active, setActive] = useState(stages[0]?.id);
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);
  useEffect(() => {
    function followHash() {
      const id = window.location.hash.slice(1);
      if (stages.some((stage) => stage.id === id)) setActive(id);
    }
    followHash();
    window.addEventListener('hashchange', followHash);
    return () => window.removeEventListener('hashchange', followHash);
  }, [stages]);

  function select(index: number, focus = false) {
    setActive(stages[index].id);
    window.history.replaceState(null, '', `#${stages[index].id}`);
    if (focus) buttons.current[index]?.focus();
  }

  return (
    <div className="ipo-stage-browser">
      <div className="ipo-stage-tabs" role="tablist" aria-label="IPO stages">
        {stages.map((stage, index) => (
          <button
            key={stage.id}
            ref={(node) => {
              buttons.current[index] = node;
            }}
            type="button"
            role="tab"
            id={`tab-${stage.id}`}
            aria-controls={`panel-${stage.id}`}
            aria-selected={active === stage.id}
            tabIndex={active === stage.id ? 0 : -1}
            onClick={() => select(index)}
            onKeyDown={(event) => {
              const next =
                event.key === 'ArrowRight'
                  ? (index + 1) % stages.length
                  : event.key === 'ArrowLeft'
                    ? (index - 1 + stages.length) % stages.length
                    : event.key === 'Home'
                      ? 0
                      : event.key === 'End'
                        ? stages.length - 1
                        : null;
              if (next !== null) {
                event.preventDefault();
                select(next, true);
              }
            }}
          >
            {stage.title}
            <span className="ipo-stage-count">{stage.count}</span>
          </button>
        ))}
      </div>
      {stages.map((stage) => (
        <div
          key={stage.id}
          id={`panel-${stage.id}`}
          role="tabpanel"
          aria-labelledby={`tab-${stage.id}`}
          hidden={active !== stage.id}
          tabIndex={0}
        >
          {stage.content}
        </div>
      ))}
    </div>
  );
}
