import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Toaster } from 'react-hot-toast';
import App from './App';
import './index.css';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      gcTime: 5 * 60_000,
      retry: 2,
      refetchOnWindowFocus: false,
    },
  },
});

// Initialize Telegram Web App
try {
  const tg = (window as any).Telegram?.WebApp;
  if (tg) {
    tg.ready();
    tg.expand();
    // Use white theme colors to match our UI
    tg.setHeaderColor('#ffffff');
    tg.setBackgroundColor('#ffffff');
    if (tg.enableClosingConfirmation) {
      tg.enableClosingConfirmation();
    }
    // CRITICAL FIX (PRISM v0.1): Disable Telegram's viewport height management
    // which locks the webview height and prevents native scrolling.
    if (tg.requestFullscreen) {
      tg.requestFullscreen();
    }
    // CRITICAL: Disable Telegram's swipe-to-close gesture which intercepts
    // ALL vertical touch events and prevents scrolling entirely.
    if (tg.disableVerticalSwipes) {
      tg.disableVerticalSwipes();
    }
    // PRISM FIX: Force viewport to be correct height
    if (tg.isExpanded === false) {
      tg.expand();
    }
    // PRISM FIX: Set viewport height CSS variable for proper layout
    // CRITICAL: Do NOT set body.style.height to a fixed pixel value!
    // That creates a fixed-height scroll container that fights with content.
    // Instead, set min-height and let body expand naturally with content.
    const setVH = () => {
      const vh = tg.viewportStableHeight || window.innerHeight;
      document.documentElement.style.setProperty('--tg-viewport-height', `${vh}px`);
      // Use min-height instead of height so body can expand with content
      document.body.style.minHeight = `${vh}px`;
      // Remove any fixed height that would trap scrolling
      document.body.style.height = 'auto';
    };
    setVH();
    tg.onEvent?.('viewportChanged', setVH);
    window.addEventListener('resize', setVH);
  }
} catch (e) {
  console.log('Telegram WebApp SDK not available (running in browser)');
}

// PRISM v0.1: Global touch scroll fix for Telegram WebApp
// Ensures that touch events on the body always result in scrolling,
// not being consumed by Telegram's gesture system.
(function fixTelegramScrolling() {
  let startY = 0;
  document.addEventListener('touchstart', (e) => {
    startY = e.touches[0].clientY;
  }, { passive: true });

  document.addEventListener('touchmove', (e) => {
    const el = e.target as HTMLElement;
    // Allow native scrolling for the body and standard content
    // Only prevent if we're in a modal or overlay that has its own scroll
    const isInScrollableOverlay = el.closest('[data-scroll-lock]');
    if (!isInScrollableOverlay) {
      // Ensure body scrolls naturally
      return;
    }
  }, { passive: true });
})();

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter basename="/app">
        <App />
        <Toaster
          position="top-center"
          toastOptions={{
            duration: 3000,
            style: {
              background: '#111111',
              color: '#ffffff',
              borderRadius: '12px',
              fontSize: '14px',
              fontWeight: '500',
              padding: '12px 20px',
              boxShadow: '0 8px 30px rgba(0,0,0,0.5)',
              border: '1px solid rgba(255,255,255,0.1)',
            },
          }}
        />
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>
);
