/* Sekelo — shared configuration.
 * Loaded before common.js and page scripts on every page.
 * Everything is attached to `window` so pages can reference bare identifiers
 * (SB_URL, SB_KEY, BORDER, BRANCHES, FLAG_THRESHOLD) without redeclaration.
 *
 * SECURITY NOTE: SB_KEY is the Supabase *anon* key — it is meant to be public.
 * It only grants what Row Level Security allows. Lock down RLS in Supabase
 * (see README → Security) so anon cannot read app_config or write to
 * price_submissions directly.
 */
window.SB_URL  = 'https://glvpdeneagsqwxzrtaln.supabase.co';
window.SB_KEY  = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImdsdnBkZW5lYWdzcXd4enJ0YWxuIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzIzODQ4NDQsImV4cCI6MjA4Nzk2MDg0NH0.y5gJY1XRFj5uGYUjnkZ9rPfLQRdub5uKBn8jIxEpdP8';
window.BORDER  = 0.20;                 // SZL border premium applied on top of ZAR
window.FLAG_THRESHOLD = 5;             // admin: % change that triggers a review flag
// `city` matches the values written to price_submissions / prices by admin.html
// (historical data uses 'Joburg' rather than 'Johannesburg').
window.BRANCHES = [
  { key:'Southgate | Cashbuild',              label:'Southgate',       source:'Cashbuild',         city:'Joburg'    },
  { key:'Nelspruit Plaza | Cashbuild',        label:'Nelspruit Plaza', source:'Cashbuild',         city:'Nelspruit' },
  { key:'Johannesburg | Builders Warehouse',  label:'Johannesburg',    source:'Builders Warehouse',city:'Joburg'    },
  { key:'Mbombela | Builders Warehouse',      label:'Mbombela',        source:'Builders Warehouse',city:'Mbombela'  },
];
