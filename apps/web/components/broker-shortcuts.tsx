'use client';

import { useState } from 'react';
import Image from 'next/image';
import { brokers } from '@/lib/brokers';

function BrokerIcon({ icon, initials }: { icon?: string; initials: string }) {
  const [failed, setFailed] = useState(false);
  return (
    <span className="broker-icon" aria-hidden="true">
      {icon && !failed ? (
        <Image
          src={icon}
          alt=""
          width={28}
          height={28}
          unoptimized
          onError={() => setFailed(true)}
        />
      ) : (
        <span>{initials}</span>
      )}
    </span>
  );
}

export function BrokerShortcuts() {
  return (
    <section className="broker-shortcuts panel" aria-labelledby="broker-shortcuts-heading">
      <div className="broker-shortcuts-intro">
        <h2 id="broker-shortcuts-heading">Apply through your broker</h2>
        <p>Opens your broker’s website. Login may be required.</p>
      </div>
      <div className="broker-shortcuts-links">
        {[...brokers]
          .sort((a, b) => a.order - b.order)
          .map((broker) => (
            <a
              className="outline-button broker-shortcut"
              key={broker.name}
              href={broker.url}
              target="_blank"
              rel="noopener noreferrer"
              aria-label={`${broker.name} (opens in a new tab)`}
            >
              <BrokerIcon icon={broker.icon} initials={broker.initials} />
              <span className="broker-shortcut-name">
                <span>{broker.name}</span>
                {'helper' in broker && <small>{broker.helper}</small>}
              </span>
              <svg
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.8"
                aria-hidden="true"
              >
                <path d="M14 3h7v7M21 3 10 14M10 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-5" />
              </svg>
            </a>
          ))}
      </div>
    </section>
  );
}
