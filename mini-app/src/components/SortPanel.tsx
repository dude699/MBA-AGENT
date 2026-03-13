// ============================================================
// SORT PANEL — Premium Sort Options Sheet
// ============================================================

import React from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, Check, ArrowUpDown } from 'lucide-react';
import { useAppStore } from '@/store/useAppStore';
import { SORT_OPTIONS } from '@/utils/constants';
import { hapticFeedback } from '@/utils/helpers';
import type { SortField } from '@/types';

export default function SortPanel() {
  const { isSortOpen, setSortOpen, sort, setSort } = useAppStore();

  if (!isSortOpen) return null;

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 z-50 bg-black/20 backdrop-blur-sm"
        onClick={() => setSortOpen(false)}
      >
        <motion.div
          initial={{ y: '100%' }}
          animate={{ y: 0 }}
          exit={{ y: '100%' }}
          transition={{ type: 'spring', damping: 30, stiffness: 300 }}
          className="absolute bottom-0 left-0 right-0 bg-white rounded-t-3xl max-h-[70vh] overflow-hidden"
          style={{ boxShadow: '0 -8px 40px rgba(0,0,0,0.08)' }}
          onClick={(e) => e.stopPropagation()}
        >
          {/* Handle */}
          <div className="flex justify-center pt-3 pb-1">
            <div className="w-10 h-1 bg-primary-200 rounded-full" />
          </div>

          {/* Header */}
          <div className="flex items-center justify-between px-5 py-3" style={{ borderBottom: '1px solid rgba(0,0,0,0.05)' }}>
            <div className="flex items-center gap-2">
              <ArrowUpDown className="w-4 h-4 text-primary-400" />
              <h2 className="text-base font-bold text-primary-900 tracking-tight">Sort By</h2>
            </div>
            <button onClick={() => setSortOpen(false)} className="p-1">
              <X className="w-5 h-5 text-primary-400" />
            </button>
          </div>

          {/* Sort Options */}
          <div className="overflow-y-auto pb-8">
            {SORT_OPTIONS.map((option) => {
              const active = sort === option.field;
              return (
                <button
                  key={option.field}
                  onClick={() => {
                    setSort(option.field);
                    hapticFeedback('light');
                    setTimeout(() => setSortOpen(false), 150);
                  }}
                  className={`flex items-center gap-3 w-full px-5 py-3 transition-all duration-200 ${
                    active ? 'bg-primary-50' : 'hover:bg-primary-50/50'
                  }`}
                >
                  <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${
                    active ? 'bg-primary-900 text-white' : 'bg-primary-50 text-primary-400'
                  }`}>
                    <ArrowUpDown className="w-3.5 h-3.5" />
                  </div>
                  <div className="flex-1 text-left">
                    <p className={`text-sm font-semibold ${active ? 'text-primary-900' : 'text-primary-700'}`}>
                      {option.label}
                    </p>
                    <p className="text-[11px] text-primary-400">{option.description}</p>
                  </div>
                  {active && (
                    <div className="w-5 h-5 rounded-full flex items-center justify-center" style={{ background: 'var(--gradient-accent)' }}>
                      <Check className="w-3 h-3 text-white" />
                    </div>
                  )}
                </button>
              );
            })}
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}
