'use client';
import { useRef } from 'react';
import { EmailSubscription } from './email-subscription';

export function ListingGainSubscription() {
  const dialog = useRef<HTMLDialogElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const risk =
    'GMP is an unofficial grey-market premium. Issue price plus GMP suggests a possible listing price, not a guarantee. GMP can change and investing can result in losses.';
  return (
    <div className="listing-gain-subscription">
      <button
        ref={trigger}
        type="button"
        className="subscription-link"
        title={risk}
        aria-describedby="subscription-risk"
        onClick={() => dialog.current?.showModal()}
      >
        Listing gain email subscription*
      </button>
      <span id="subscription-risk" className="subscription-risk" role="tooltip">
        {risk}
      </span>
      <dialog
        ref={dialog}
        className="subscription-dialog"
        aria-label="Listing gain email subscription"
        onClose={() => trigger.current?.focus()}
      >
        <button
          type="button"
          className="subscription-close"
          onClick={() => dialog.current?.close()}
        >
          Close ✕
        </button>
        <EmailSubscription />
      </dialog>
    </div>
  );
}
