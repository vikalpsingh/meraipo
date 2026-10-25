// Official destinations checked 2026-10-25. Asset sources: public/brokers/SOURCES.md.
export const brokers = [
  {
    name: 'Zerodha',
    url: 'https://kite.zerodha.com/',
    icon: '/brokers/zerodha.png',
    initials: 'Z',
    order: 1,
    helper: 'Bids → IPO',
  },
  {
    name: 'Groww',
    url: 'https://groww.in/ipo',
    icon: '/brokers/groww.ico',
    initials: 'G',
    order: 2,
  },
  {
    name: 'Angel One',
    url: 'https://www.angelone.in/upcoming-ipo',
    icon: '/brokers/angel-one.ico',
    initials: 'AO',
    order: 3,
  },
  {
    name: 'Upstox',
    url: 'https://upstox.com/ipo/',
    icon: '/brokers/upstox.png',
    initials: 'U',
    order: 4,
  },
] as const;
