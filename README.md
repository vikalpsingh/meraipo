# MeraIPO

An IPO research dashboard with three public routes and a protected maintenance console.

- `/`: current and upcoming IPO cards.
- `/tracker`: historical issue, listing, price-return and latest quarterly comparison.
- `/company/[id]`: company-level quarterly financial history and source records.
- `/meraadmin`: server-authorized maintenance for vikalp.singh@gmail.com through ChatGPT sign-in.

## Current data status
All companies and initial financial figures are fictional samples. No live feeds, exchange scraping, market-data licensing, or scheduled import jobs are configured. Provider interfaces in `lib/providers.ts` separate pages from future data integrations. D1 persists manual GMP and quarterly updates; existing-quarter saves replace that quarter. Admin writes validate values and source links and record the actor and update time.

## Development
Node 22.13+ is required. Run `npm run install:ci`, then `npm run dev`. Run `npm run build` for the production Worker. `npx tsc --noEmit` checks types.

The Sites runtime provides Cloudflare D1 and trusted authentication headers. Local development simulates a non-admin account, deliberately excluding it from the production administrator allowlist. Never expose a directly accessible Worker that accepts untrusted identity headers.

Generate migrations with `npm run db:generate`. After a build, apply pending local migrations with `node --import ./scripts/sites-env.mjs ./node_modules/wrangler/bin/wrangler.js d1 execute DB --local --config dist/server/wrangler.json --persist-to .wrangler/state --file drizzle/0000_short_mentallo.sql`. Sites applies production migrations during publication.

## Next integration milestone
Add verified real-company master records, official filing URLs, a licensed price feed, provenance-aware data labels, corporate-action handling, result validation, and scheduled provider imports before offering live research. The current admin console maintains sample-company records only.
