import { test as base, expect } from '@playwright/test';

export const test = base.extend<{ runtimeErrors: string[] }>({
  runtimeErrors: [
    async ({ page }, use) => {
      const errors: string[] = [];
      page.on('pageerror', (error) => errors.push(error.message));
      page.on('console', (message) => {
        if (message.type() === 'error' && /hydration|hydrated/i.test(message.text()))
          errors.push(message.text());
      });
      await use(errors);
      expect(errors, 'The browser must have no uncaught JavaScript or hydration errors').toEqual(
        [],
      );
    },
    { auto: true },
  ],
});
export { expect };
