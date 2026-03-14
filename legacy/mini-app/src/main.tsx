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
  const tg = window.Telegram?.WebApp;
  if (tg) {
    tg.ready();
    tg.expand();
    tg.setHeaderColor('#000000');
    tg.setBackgroundColor('#000000');
    if (tg.enableClosingConfirmation) {
      tg.enableClosingConfirmation();
    }
  }
} catch (e) {
  console.log('Telegram WebApp SDK not available (running in browser)');
}

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
