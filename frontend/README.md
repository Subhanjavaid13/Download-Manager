# frontend

Next.js 16 app for Downloader Manager. See the [root README](../README.md) for the full picture.

```bash
npm install
cp .env.local.example .env.local   # NEXT_PUBLIC_API_URL, defaults to http://localhost:8000
npm run dev                         # http://localhost:3000
```

- `src/components/downloader.tsx`: the whole flow (paste, preview, mode, quality, progress, save).
- `src/lib/api.ts`: typed client for the FastAPI backend; `setTokenProvider` hooks in Supabase auth (Phase 2).
- `src/app/manifest.ts`: PWA manifest with an Android share target so the YouTube app can share into this app.
- `src/app/globals.css`: design tokens for light and dark themes.
