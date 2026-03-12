// ============================================================
// HEADER COMPONENT — Premium Telegram Mini App Header
// ============================================================

import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Search, SlidersHorizontal, ArrowUpDown, Sparkles, BarChart3,
  X, ChevronDown, Shield, Zap, Clock
} from 'lucide-react';
import { useAppStore } from '@/store/useAppStore';
import { hapticFeedback } from '@/utils/helpers';
import { useDebounce } from '@/hooks/useHooks';

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
    // Debounced via effect
    setTimeout(() => setSearch(value), 300);
  };

  return (
    <header className="sticky top-0 z-40 bg-white/95 backdrop-blur-md border-b border-surface-border">
      {/* Top Bar */}
      <div className="px-4 pt-3 pb-2">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 bg-accent rounded-xl flex items-center justify-center">
              <Zap className="w-4 h-4 text-white" />
            </div>
            <div>
              <h1 className="text-base font-bold text-primary-950 leading-tight">
                InternHub Pro
              </h1>
              <p className="text-[10px] text-primary-500 font-medium tracking-wide uppercase">
                {totalCount.toLocaleString()} Internships
              </p>
            </div>
          </div>

          <div className="flex items-center gap-1.5">
            <button
              onClick={() => { setLLMPanelOpen(!isLLMPanelOpen); hapticFeedback('light'); }}
              className={`p-2 rounded-xl transition-all duration-200 ${
                isLLMPanelOpen ? 'bg-accent text-white' : 'bg-surface-muted text-primary-700 hover:bg-surface-light'
              }`}
            >
              <Sparkles className="w-4 h-4" />
            </button>
            <button
              onClick={() => { window.location.hash = '#analytics'; hapticFeedback('light'); }}
              className="p-2 rounded-xl bg-surface-muted text-primary-700 hover:bg-surface-light transition-all"
            >
              <BarChart3 className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Search Bar */}
        <div className={`relative transition-all duration-200 ${searchFocused ? 'ring-2 ring-accent/20' : ''} rounded-xl`}>
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-primary-400" />
          <input
            type="text"
            value={searchValue}
            onChange={(e) => handleSearchChange(e.target.value)}
            onFocus={() => setSearchFocused(true)}
            onBlur={() => setSearchFocused(false)}
            placeholder="Search internships, companies, skills..."
            className="w-full pl-10 pr-10 py-2.5 bg-surface-muted border border-surface-border rounded-xl text-sm text-primary-900 placeholder-primary-400 focus:outline-none focus:bg-white transition-all"
          />
          {searchValue && (
            <button
              onClick={() => { handleSearchChange(''); hapticFeedback('light'); }}
              className="absolute right-3 top-1/2 -translate-y-1/2 p-0.5 rounded-full bg-primary-200 hover:bg-primary-300"
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
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
            isFilterOpen || activeFilterCount > 0
              ? 'bg-accent text-white'
              : 'bg-surface-muted text-primary-700 border border-surface-border hover:border-primary-400'
          }`}
        >
          <SlidersHorizontal className="w-3.5 h-3.5" />
          <span>Filters</span>
          {activeFilterCount > 0 && (
            <span className="bg-white/20 text-white text-[10px] px-1.5 py-0.5 rounded-full font-bold">
              {activeFilterCount}
            </span>
          )}
        </button>

        {/* Sort Button */}
        <button
          onClick={() => { setSortOpen(!isSortOpen); hapticFeedback('light'); }}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-surface-muted text-primary-700 border border-surface-border hover:border-primary-400 transition-all"
        >
          <ArrowUpDown className="w-3.5 h-3.5" />
          <span>Sort</span>
        </button>

        {/* Quick Filter Chips */}
        <div className="flex-1 overflow-x-auto scrollbar-none flex items-center gap-1.5">
          <QuickChip
            label="≤3 Mo"
            icon={<Clock className="w-3 h-3" />}
            active={filters.durationMax <= 3}
            onClick={() => useAppStore.getState().setFilters({ durationMax: filters.durationMax <= 3 ? 12 : 3 })}
          />
          <QuickChip
            label="Paid"
            icon={<span className="text-[10px]">₹</span>}
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
            className="overflow-hidden border-t border-surface-border"
          >
            <div className="px-4 py-2 bg-accent/5 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <div className="w-5 h-5 bg-accent rounded-md flex items-center justify-center">
                  <span className="text-white text-[10px] font-bold">{selectedIds.size}</span>
                </div>
                <span className="text-xs font-medium text-primary-700">
                  Selected from <span className="font-bold text-accent capitalize">{lockedSource}</span>
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
      className={`flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-semibold whitespace-nowrap transition-all ${
        active
          ? 'bg-accent text-white'
          : 'bg-white text-primary-600 border border-surface-border hover:border-primary-400'
      }`}
    >
      {icon}
      {label}
    </button>
  );
}
