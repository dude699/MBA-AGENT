// ============================================================
// HEADER — Ultra Premium Telegram Mini App Header
// ============================================================

import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Search, SlidersHorizontal, ArrowUpDown, Sparkles,
  X, Shield, Clock
} from 'lucide-react';
import { useAppStore } from '@/store/useAppStore';
import { hapticFeedback } from '@/utils/helpers';

export default function Header() {
  const {
    filters, activeFilterCount, sort, totalCount,
    isFilterOpen, isSortOpen, isLLMPanelOpen,
    setFilterOpen, setSortOpen, setLLMPanelOpen, setSearch,
    selectedIds, lockedSource,
  } = useAppStore();

  const [searchFocused, setSearchFocused] = useState(false);
  const [searchValue, setSearchValue] = useState(filters.search);

  const handleSearchChange = (value: string) => {
    setSearchValue(value);
    setTimeout(() => setSearch(value), 300);
  };

  return (
    <header className="sticky top-0 z-30" style={{
      background: 'rgba(255,255,255,0.92)',
      backdropFilter: 'blur(20px) saturate(180%)',
      WebkitBackdropFilter: 'blur(20px) saturate(180%)',
      borderBottom: '1px solid rgba(0,0,0,0.06)',
    }}>
      {/* Top Bar */}
      <div className="px-4 pt-3 pb-2">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2.5">
            <div className="w-9 h-9 rounded-xl flex items-center justify-center" style={{ background: 'var(--gradient-accent)' }}>
              <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" />
              </svg>
            </div>
            <div>
              <h1 className="text-base font-bold text-primary-950 leading-tight tracking-tight">
                InternHub Pro
              </h1>
              <p className="text-[10px] text-primary-400 font-medium tracking-wider uppercase">
                {totalCount.toLocaleString()} Opportunities
              </p>
            </div>
          </div>

          <div className="flex items-center gap-1.5">
            <button
              onClick={() => { setLLMPanelOpen(!isLLMPanelOpen); hapticFeedback('light'); }}
              className="relative p-2 rounded-xl transition-all duration-200"
              style={isLLMPanelOpen ? { background: 'var(--gradient-ai)', color: 'white' } : { background: '#f4f4f6', color: '#495057' }}
            >
              <Sparkles className="w-4 h-4" />
              <span className="absolute -top-0.5 -right-0.5 w-2 h-2 rounded-full bg-emerald-400 border border-white" />
            </button>
          </div>
        </div>

        {/* Search Bar - Premium Glass */}
        <div className={`relative transition-all duration-300 rounded-xl ${searchFocused ? 'ring-2 ring-primary-900/8' : ''}`}>
          <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-primary-300" />
          <input
            type="text"
            value={searchValue}
            onChange={(e) => handleSearchChange(e.target.value)}
            onFocus={() => setSearchFocused(true)}
            onBlur={() => setSearchFocused(false)}
            placeholder="Search companies, roles, skills..."
            className="w-full pl-10 pr-10 py-2.5 bg-primary-50/80 border border-primary-100 rounded-xl text-sm text-primary-900 placeholder-primary-400 focus:outline-none focus:bg-white focus:border-primary-200 transition-all duration-300"
          />
          {searchValue && (
            <button
              onClick={() => { handleSearchChange(''); hapticFeedback('light'); }}
              className="absolute right-3 top-1/2 -translate-y-1/2 p-0.5 rounded-full bg-primary-200 hover:bg-primary-300 transition-colors"
            >
              <X className="w-3 h-3 text-primary-700" />
            </button>
          )}
        </div>
      </div>

      {/* Action Bar */}
      <div className="px-4 pb-2.5 flex items-center gap-2">
        {/* Filter Button */}
        <button
          onClick={() => { setFilterOpen(!isFilterOpen); hapticFeedback('light'); }}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all duration-200 ${
            isFilterOpen || activeFilterCount > 0
              ? 'text-white shadow-sm'
              : 'bg-white text-primary-700 border border-primary-200/60 hover:border-primary-300'
          }`}
          style={(isFilterOpen || activeFilterCount > 0) ? { background: 'var(--gradient-accent)' } : {}}
        >
          <SlidersHorizontal className="w-3.5 h-3.5" />
          <span>Filters</span>
          {activeFilterCount > 0 && (
            <span className="bg-white/20 text-white text-[10px] px-1.5 py-0.5 rounded-full font-bold min-w-[18px] text-center">
              {activeFilterCount}
            </span>
          )}
        </button>

        {/* Sort Button */}
        <button
          onClick={() => { setSortOpen(!isSortOpen); hapticFeedback('light'); }}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-white text-primary-700 border border-primary-200/60 hover:border-primary-300 transition-all duration-200"
        >
          <ArrowUpDown className="w-3.5 h-3.5" />
          <span>Sort</span>
        </button>

        {/* Quick Filter Chips */}
        <div className="flex-1 overflow-x-auto scrollbar-none flex items-center gap-1.5">
          <QuickChip
            label="<3 Mo"
            icon={<Clock className="w-3 h-3" />}
            active={filters.durationMax <= 3}
            onClick={() => useAppStore.getState().setFilters({ durationMax: filters.durationMax <= 3 ? 12 : 3 })}
          />
          <QuickChip
            label="Paid"
            icon={<span className="text-[10px] font-bold">INR</span>}
            active={filters.onlyWithStipend}
            onClick={() => useAppStore.getState().setFilters({ onlyWithStipend: !filters.onlyWithStipend })}
          />
          <QuickChip
            label="Remote"
            active={filters.locationTypes.includes('remote')}
            onClick={() => {
              const types = filters.locationTypes.includes('remote')
                ? filters.locationTypes.filter((t) => t !== 'remote')
                : [...filters.locationTypes, 'remote' as const];
              useAppStore.getState().setFilters({ locationTypes: types });
            }}
          />
          <QuickChip
            label="Verified"
            icon={<Shield className="w-3 h-3" />}
            active={filters.onlyVerified}
            onClick={() => useAppStore.getState().setFilters({ onlyVerified: !filters.onlyVerified })}
          />
        </div>
      </div>

      {/* Selection Bar */}
      <AnimatePresence>
        {selectedIds.size > 0 && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden"
            style={{ borderTop: '1px solid rgba(0,0,0,0.04)' }}
          >
            <div className="px-4 py-2 flex items-center justify-between" style={{ background: 'rgba(26,26,46,0.03)' }}>
              <div className="flex items-center gap-2">
                <div className="w-5 h-5 rounded-md flex items-center justify-center text-white" style={{ background: 'var(--gradient-accent)' }}>
                  <span className="text-[10px] font-bold">{selectedIds.size}</span>
                </div>
                <span className="text-xs font-medium text-primary-700">
                  Selected from <span className="font-bold text-primary-900 capitalize">{lockedSource}</span>
                </span>
              </div>
              <button
                onClick={() => { useAppStore.getState().deselectAll(); hapticFeedback('light'); }}
                className="text-xs font-semibold text-status-danger hover:underline"
              >
                Clear All
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </header>
  );
}

// ===== QUICK CHIP COMPONENT =====
function QuickChip({
  label, icon, active, onClick
}: {
  label: string; icon?: React.ReactNode; active: boolean; onClick: () => void;
}) {
  return (
    <button
      onClick={() => { onClick(); hapticFeedback('light'); }}
      className={`flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-semibold whitespace-nowrap transition-all duration-200 ${
        active
          ? 'text-white shadow-sm'
          : 'bg-white text-primary-600 border border-primary-200/60 hover:border-primary-300'
      }`}
      style={active ? { background: 'var(--gradient-accent)' } : {}}
    >
      {icon}
      {label}
    </button>
  );
}
