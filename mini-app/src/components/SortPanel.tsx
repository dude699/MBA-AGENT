// ============================================================
// SORT PANEL — v4.0: CSS-only animation, zero mobile glitch
// ============================================================

import React, { useState, useEffect, useCallback } from 'react';
import { X, Check, ArrowUpDown } from 'lucide-react';
import { useAppStore } from '@/store/useAppStore';
import { SORT_OPTIONS } from '@/utils/constants';
import { hapticFeedback } from '@/utils/helpers';

export default function SortPanel() {
  const { isSortOpen, setSortOpen, sort, setSort } = useAppStore();
  const [isVisible, setIsVisible] = useState(false);

  useEffect(() => {
    if (isSortOpen) {
      requestAnimationFrame(() => setIsVisible(true));
      document.body.style.overflow = 'hidden';
    } else {
      setIsVisible(false);
      document.body.style.overflow = '';
    }
    return () => { document.body.style.overflow = ''; };
  }, [isSortOpen]);

  const handleClose = useCallback(() => {
    setIsVisible(false);
    setTimeout(() => setSortOpen(false), 250);
  }, [setSortOpen]);

  if (!isSortOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50"
      style={{
        backgroundColor: isVisible ? 'rgba(0,0,0,0.2)' : 'rgba(0,0,0,0)',
        transition: 'background-color 0.25s ease',
      }}
      onClick={(e) => { if (e.target === e.currentTarget) handleClose(); }}
    >
      <div
        style={{
          position: 'absolute',
          bottom: 0,
          left: 0,
          right: 0,
          maxHeight: '70vh',
          background: '#ffffff',
          borderRadius: '24px 24px 0 0',
          boxShadow: '0 -8px 40px rgba(0,0,0,0.08)',
          overflow: 'hidden',
          transform: isVisible ? 'translateY(0)' : 'translateY(100%)',
          transition: 'transform 0.3s cubic-bezier(0.22, 1, 0.36, 1)',
          willChange: 'transform',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Handle */}
        <div className="flex justify-center pt-3 pb-1">
          <div className="w-10 h-1 bg-gray-200 rounded-full" />
        </div>

        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3" style={{ borderBottom: '1px solid rgba(0,0,0,0.05)' }}>
          <div className="flex items-center gap-2">
            <ArrowUpDown className="w-4 h-4 text-gray-400" />
            <h2 className="text-base font-bold text-gray-900 tracking-tight">Sort By</h2>
          </div>
          <button onClick={handleClose} className="p-1">
            <X className="w-5 h-5 text-gray-400" />
          </button>
        </div>

        {/* Sort Options */}
        <div
          className="overflow-y-auto overscroll-contain"
          style={{
            paddingBottom: 'calc(24px + env(safe-area-inset-bottom, 0px))',
            WebkitOverflowScrolling: 'touch',
          }}
        >
          {SORT_OPTIONS.map((option) => {
            const active = sort === option.field;
            return (
              <button
                key={option.field}
                onClick={(e) => {
                  e.stopPropagation();
                  setSort(option.field);
                  hapticFeedback('light');
                  setTimeout(handleClose, 150);
                }}
                className={`flex items-center gap-3 w-full px-5 py-3 ${
                  active ? 'bg-gray-50' : 'active:bg-gray-50/50'
                }`}
              >
                <div
                  className="w-8 h-8 rounded-lg flex items-center justify-center"
                  style={{
                    background: active ? '#0a0a0a' : '#f3f4f6',
                    color: active ? '#ffffff' : '#9ca3af',
                  }}
                >
                  <ArrowUpDown className="w-3.5 h-3.5" />
                </div>
                <div className="flex-1 text-left">
                  <p className={`text-sm font-semibold ${active ? 'text-gray-900' : 'text-gray-700'}`}>
                    {option.label}
                  </p>
                  <p className="text-[11px] text-gray-400">{option.description}</p>
                </div>
                {active && (
                  <div className="w-5 h-5 rounded-full flex items-center justify-center"
                    style={{ background: 'linear-gradient(135deg, #0a0a0a 0%, #374151 100%)' }}>
                    <Check className="w-3 h-3 text-white" />
                  </div>
                )}
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
