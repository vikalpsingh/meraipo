import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, expect, it } from 'vitest';
import { IPOStageTabs } from '@/components/ipo-stage-tabs';

const stages = [
  { id: 'open', title: 'Open for subscription', count: 12, content: <p>Open companies</p> },
  { id: 'upcoming', title: 'Coming next', count: 2, content: <p>Upcoming companies</p> },
  { id: 'announced', title: 'Announced · dates awaited', count: 0, content: <p>No issues</p> },
];
beforeEach(() => window.history.replaceState(null, '', '/'));

it('defaults to open and shows only the selected stage', () => {
  render(<IPOStageTabs stages={stages} />);
  expect(screen.getByRole('tabpanel')).toHaveTextContent('Open companies');
  fireEvent.click(screen.getByRole('tab', { name: /Coming next/ }));
  expect(screen.getByRole('tabpanel')).toHaveTextContent('Upcoming companies');
  expect(screen.getByText('Open companies')).not.toBeVisible();
  expect(window.location.hash).toBe('#upcoming');
});

it('supports arrow, Home and End keys, including empty stages', () => {
  render(<IPOStageTabs stages={stages} />);
  fireEvent.keyDown(screen.getByRole('tab', { name: /Open for/ }), { key: 'ArrowLeft' });
  expect(screen.getByRole('tab', { name: /Announced/ })).toHaveFocus();
  expect(screen.getByRole('tabpanel')).toHaveTextContent('No issues');
  fireEvent.keyDown(document.activeElement!, { key: 'Home' });
  expect(screen.getByRole('tab', { name: /Open for/ })).toHaveFocus();
  fireEvent.keyDown(document.activeElement!, { key: 'End' });
  expect(screen.getByRole('tab', { name: /Announced/ })).toHaveFocus();
});

it('opens a stage from an existing link and follows hash navigation', () => {
  window.history.replaceState(null, '', '#announced');
  render(<IPOStageTabs stages={stages} />);
  expect(screen.getByRole('tabpanel')).toHaveTextContent('No issues');
  window.history.replaceState(null, '', '#upcoming');
  fireEvent(window, new Event('hashchange'));
  expect(screen.getByRole('tabpanel')).toHaveTextContent('Upcoming companies');
});
