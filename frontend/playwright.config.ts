import { defineConfig } from '@playwright/test'

// Responsive checks at the three target widths. The tests mock /api so they do
// not need the backend; they verify layout only.
export default defineConfig({
  testDir: './e2e',
  reporter: [['list']],
  use: {
    baseURL: 'http://localhost:5173',
    // Optional: run against an already-installed Chrome instead of downloading
    // Playwright's Chromium, e.g. PLAYWRIGHT_CHROME_PATH=/usr/bin/google-chrome
    launchOptions: {
      executablePath: process.env.PLAYWRIGHT_CHROME_PATH || undefined,
    },
  },
  projects: [
    { name: 'phone-360', use: { browserName: 'chromium', viewport: { width: 360, height: 740 } } },
    { name: 'tablet-768', use: { browserName: 'chromium', viewport: { width: 768, height: 1024 } } },
    { name: 'desktop-1280', use: { browserName: 'chromium', viewport: { width: 1280, height: 800 } } },
  ],
  webServer: {
    command: 'npm run dev -- --port 5173 --strictPort',
    url: 'http://localhost:5173',
    reuseExistingServer: true,
    timeout: 60_000,
  },
})
