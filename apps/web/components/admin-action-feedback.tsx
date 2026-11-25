'use client';
import {
  createContext,
  useContext,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { createPortal } from 'react-dom';

const ActionTarget = createContext<{ current: HTMLElement | null } | null>(null);

export function adminMessage(value: string) {
  const messages: Record<string, string> = {
    OPENAI_QUOTA_EXHAUSTED:
      'OpenAI API quota or billing limit reached. Check billing, credits and usage limits for the project that owns the server API key. X credits do not fund OpenAI requests. Retrying will not fix exhausted quota. (OPENAI_QUOTA_EXHAUSTED)',
    OPENAI_RATE_LIMITED:
      'OpenAI temporarily rate-limited this request. Wait before retrying and check project/model rate limits. No X post was sent. (OPENAI_RATE_LIMITED)',
    OPENAI_HTTP_429:
      'OpenAI rejected the request with HTTP 429. This can mean exhausted API quota or a temporary rate limit; this saved error does not distinguish them. Check OpenAI project billing and rate limits. (OPENAI_HTTP_429)',
    OPENAI_HTTP_401:
      'OpenAI rejected the server API key. Check that it is valid and has not been revoked. (OPENAI_HTTP_401)',
  };
  return messages[value] || value;
}

export function AdminFeedbackBoundary({ children }: { children: ReactNode }) {
  const target = useRef<HTMLElement | null>(null);
  return (
    <ActionTarget.Provider value={target}>
      <div
        style={{ display: 'contents' }}
        onClickCapture={(event) => {
          const button = (event.target as HTMLElement).closest<HTMLElement>(
            'button, input[type="submit"]',
          );
          if (button && !button.closest('nav')) target.current = button;
        }}
        onChangeCapture={(event) => {
          target.current = event.target as HTMLElement;
        }}
        onSubmitCapture={(event) => {
          const submitter = (event.nativeEvent as SubmitEvent).submitter;
          target.current = submitter || (event.target as HTMLElement);
        }}
      >
        {children}
      </div>
    </ActionTarget.Provider>
  );
}

/** Keep action results beside their trigger without scrolling or stealing focus. */
export function AdminActionFeedback({
  children,
  role = 'status',
}: {
  children: ReactNode;
  role?: 'status' | 'alert';
}) {
  const target = useContext(ActionTarget);
  const [slot, setSlot] = useState<HTMLElement | null>(null);
  useLayoutEffect(() => {
    const trigger = target?.current;
    if (!children || !trigger?.isConnected) {
      // The portal target is an external DOM node; synchronize before paint to avoid a top-page flash.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setSlot(null);
      return;
    }
    const holder = document.createElement('div');
    holder.className = 'admin-action-feedback-slot';
    trigger.insertAdjacentElement('afterend', holder);
    setSlot(holder);
    return () => holder.remove();
  }, [children, target]);
  if (!children) return null;
  const feedback = (
    <p
      className="admin-action-feedback"
      role={role}
      aria-live={role === 'alert' ? 'assertive' : 'polite'}
      aria-atomic="true"
    >
      {typeof children === 'string' ? adminMessage(children) : children}
    </p>
  );
  return slot ? createPortal(feedback, slot) : feedback;
}
