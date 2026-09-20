import { render, screen } from '@testing-library/react';
import { it, expect } from 'vitest';
import { Message, Ads } from '../../components/content';
it('renders nothing when optional editorial content is absent', () => {
  const { container } = render(
    <>
      <Message message={null} />
      <Ads items={[]} />
    </>,
  );
  expect(container).toBeEmptyDOMElement();
});
it('renders investing thoughts as escaped plain text with attribution', () => {
  render(
    <Message
      message={{
        id: '1',
        title: 'Perspective',
        content: '<script>alert(1)</script>',
        attribution: 'MeraIPO editorial',
        kind: 'quote',
        enabled: true,
        active_from: null,
        active_to: null,
      }}
    />,
  );
  expect(screen.getByText('— MeraIPO editorial')).toBeInTheDocument();
  expect(document.querySelector('script')).toBeNull();
  expect(screen.getByText(/<script>/)).toBeInTheDocument();
});
it('labels configured advertisements', () => {
  render(
    <Ads
      items={[
        {
          id: '1',
          text: 'Research tools',
          destination_url: 'https://example.com',
          image_url: null,
          placement: 'home',
          enabled: true,
        },
      ]}
    />,
  );
  expect(screen.getByText('ADVERTISEMENT')).toBeInTheDocument();
  expect(screen.getByRole('link')).toHaveAttribute('rel', 'sponsored noopener noreferrer');
});
