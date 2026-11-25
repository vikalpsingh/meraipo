import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { useState } from 'react';
import { expect, it } from 'vitest';
import { AdminActionFeedback, AdminFeedbackBoundary } from '../../components/admin-action-feedback';

function Example() {
  const [message, setMessage] = useState('');
  return (
    <AdminFeedbackBoundary>
      <header>
        <AdminActionFeedback>{message}</AdminActionFeedback>
      </header>
      <section aria-label="OpenAI">
        <button onClick={() => setMessage('OPENAI_QUOTA_EXHAUSTED')}>Test</button>
      </section>
      <section aria-label="Email">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            setMessage('Email queued');
          }}
        >
          <button>Send</button>
        </form>
      </section>
    </AdminFeedbackBoundary>
  );
}
it('shows feedback beside the originating action and cleans up on unmount', async () => {
  const view = render(<Example />);
  fireEvent.click(screen.getByText('Test'));
  await waitFor(() =>
    expect(screen.getByRole('status').closest('section')).toHaveAttribute('aria-label', 'OpenAI'),
  );
  expect(screen.getByRole('status')).toHaveTextContent('OpenAI API quota or billing limit reached');
  expect(view.container.querySelector('header')).not.toHaveTextContent('quota');
  fireEvent.click(screen.getByText('Send'));
  await waitFor(() =>
    expect(screen.getByRole('status').closest('section')).toHaveAttribute('aria-label', 'Email'),
  );
  expect(screen.getByRole('status')).toHaveTextContent('Email queued');
  view.unmount();
  expect(document.querySelector('.admin-action-feedback-slot')).toBeNull();
});
it('keeps initial load failures inline without an action', () => {
  render(
    <AdminFeedbackBoundary>
      <section>
        <AdminActionFeedback role="alert">Could not load</AdminActionFeedback>
      </section>
    </AdminFeedbackBoundary>,
  );
  expect(screen.getByRole('alert')).toHaveTextContent('Could not load');
});
