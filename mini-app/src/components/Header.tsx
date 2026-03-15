// ============================================================
// HEADER — PRISM v0.1 Ultra Premium Frosted Glass Header
// Premium micro-animations, depth effects, smooth transitions
// ============================================================

import React, { useState, useCallback, useRef, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Search, SlidersHorizontal, ArrowUpDown, Sparkles,
  X, Shield, Clock, Zap
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
  const searchTimeoutRef = useRef<NodeJS.Timeout>();

  // Debounced search
  const handleSearchChange = useCallback((value: string) => {
    setSearchValue(value);
    if (searchTimeoutRef.current) clearTimeout(searchTimeoutRef.current);
    searchTimeoutRef.current = setTimeout(() => setSearch(value), 250);
  }, [setSearch]);

  useEffect(() => {
    return () => {
      if (searchTimeoutRef.current) clearTimeout(searchTimeoutRef.current);
    };
  }, []);

  return (
    <header className="sticky top-0 z-30" style={{
      background: 'rgba(5,5,8,0.95)',
      backdropFilter: 'blur(24px) saturate(180%)',
      WebkitBackdropFilter: 'blur(24px) saturate(180%)',
      borderBottom: '1px solid rgba(255,255,255,0.05)',
    }}>
      {/* Top Bar */}
      <div className="px-4 pt-3 pb-2">
        <div className="flex items-center justify-between mb-3">
          {/* Brand */}
          <div className="flex items-center gap-3">
            <motion.div
              className="w-10 h-10 rounded-xl flex items-center justify-center relative overflow-hidden"
              style={{
                background: 'linear-gradient(135deg, #ffffff 0%, #f0f0f0 100%)',
                boxShadow: '0 2px 12px rgba(255,255,255,0.15)',
              }}
              whileTap={{ scale: 0.92 }}
            >
              <Zap className="w-5 h-5 text-black" strokeWidth={2.5} />
              {/* Subtle shine effect */}
              <div
                className="absolute inset-0 opacity-30"
                style={{
                  background: 'linear-gradient(135deg, transparent 40%, rgba(255,255,255,0.8) 50%, transparent 60%)',
                }}
              />
            </motion.div>
            <div>
              <h1 className="text-[15px] font-bold leading-tight tracking-tight" style={{ color: '#ffffff' }}>
                InternHub Pro
              </h1>
              <div className="flex items-center gap-1.5">
                <div className="w-1.5 h-1.5 rounded-full bg-emerald-400" style={{ boxShadow: '0 0 6px rgba(52,211,153,0.5)' }} />
                <p className="text-[10px] font-medium tracking-wide" style={{ color: 'rgba(255,255,255,0.45)' }}>
                  {totalCount > 0 ? `${totalCount.toLocaleString()} Opportunities` : 'PRISM Intelligence Active'}
                </p>
              </div>
            </div>
          </div>

          {/* AI Sparkles Button */}
          <motion.button
            onClick={() => { setLLMPanelOpen(!isLLMPanelOpen); hapticFeedback('light'); }}
            className="relative p-2.5 rounded-xl"
            style={{
              background: isLLMPanelOpen
                ? 'linear-gradient(135deg, #6366f1, #8b5cf6)'
                : 'rgba(255,255,255,0.06)',
              boxShadow: isLLMPanelOpen ? '0 4px 16px rgba(99,102,241,0.3)' : 'none',
            }}
            whileTap={{ scale: 0.9 }}
            whileHover={{ scale: 1.05 }}
            transition={{ type: 'spring', stiffness: 400, damping: 15 }}
          >
            <Sparkles className="w-[18px] h-[18px]" style={{ color: isLLMPanelOpen ? '#fff' : 'rgba(255,255,255,0.5)' }} />
            <span
              className="absolute -top-0.5 -right-0.5 w-2.5 h-2.5 rounded-full border-2"
              style={{
                background: '#10b981',
                borderColor: 'rgba(5,5,8,0.95)',
                boxShadow: '0 0 6px rgba(16,185,129,0.4)',
              }}
            />
          </motion.button>
        </div>

        {/* Search Bar */}
        <motion.div
          className="relative rounded-xl overflow-hidden"
          animate={{
            boxShadow: searchFocused
              ? '0 0 0 2px rgba(255,255,255,0.1), 0 4px 16px rgba(0,0,0,0.2)'
              : '0 0 0 1px rgba(255,255,255,0.06)',
          }}
          transition={{ duration: 0.25 }}
        >
          <Search
            className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 transition-colors duration-200"
            style={{ color: searchFocused ? 'rgba(255,255,255,0.6)' : 'rgba(255,255,255,0.25)' }}
          />
          <input
            type="text"
            value={searchValue}
            onChange={(e) => handleSearchChange(e.target.value)}
            onFocus={() => setSearchFocused(true)}
            onBlur={() => setSearchFocused(false)}
            placeholder="Search companies, roles, skills..."
            className="w-full pl-10 pr-10 py-2.5 rounded-xl text-sm text-white placeholder-white/25 focus:outline-none transition-all duration-300"
            style={{
              background: searchFocused ? 'rgba(255,255,255,0.08)' : 'rgba(255,255,255,0.04)',
            }}
          />
          <AnimatePresence>
            {searchValue && (
              <motion.button
                initial={{ opacity: 0, scale: 0.8 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.8 }}
                onClick={() => { handleSearchChange(''); hapticFeedback('light'); }}
                className="absolute right-3 top-1/2 -translate-y-1/2 p-1 rounded-full transition-colors"
                style={{ background: 'rgba(255,255,255,0.1)' }}
              >
                <X className="w-3 h-3 text-white/60" />
              </motion.button>
            )}
          </AnimatePresence>
        </motion.div>
      </div>

      {/* Action Bar */}
      <div className="px-4 pb-2.5 flex items-center gap-2">
        {/* Filter Button */}
        <motion.button
          onClick={() => { setFilterOpen(!isFilterOpen); hapticFeedback('light'); }}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all duration-200 ${
            isFilterOpen || activeFilterCount > 0
              ? 'bg-white text-black'
              : 'text-white/60 hover:text-white/80'
          }`}
          style={{
            border: isFilterOpen || activeFilterCount > 0 ? 'none' : '1px solid rgba(255,255,255,0.08)',
            boxShadow: isFilterOpen || activeFilterCount > 0 ? '0 2px 8px rgba(255,255,255,0.1)' : 'none',
          }}
          whileTap={{ scale: 0.95 }}
        >
          <SlidersHorizontal className="w-3.5 h-3.5" />
          <span>Filters</span>
          <AnimatePresence>
            {activeFilterCount > 0 && (
              <motion.span
                initial={{ scale: 0 }}
                animate={{ scale: 1 }}
                exit={{ scale: 0 }}
                className="text-[10px] px-1.5 py-0.5 rounded-full font-bold min-w-[18px] text-center"
                style={{
                  background: isFilterOpen || activeFilterCount > 0 ? '#0a0a0a' : 'rgba(255,255,255,0.15)',
                  color: isFilterOpen || activeFilterCount > 0 ? '#fff' : '#fff',
                }}
              >
                {activeFilterCount}
              </motion.span>
            )}
          </AnimatePresence>
        </motion.button>

        {/* Sort Button */}
        <motion.button
          onClick={() => { setSortOpen(!isSortOpen); hapticFeedback('light'); }}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold text-white/60 hover:text-white/80 transition-all duration-200"
          style={{ border: '1px solid rgba(255,255,255,0.08)' }}
          whileTap={{ scale: 0.95 }}
        >
          <ArrowUpDown className="w-3.5 h-3.5" />
          <span>Sort</span>
        </motion.button>

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
            transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
            className="overflow-hidden"
            style={{ borderTop: '1px solid rgba(255,255,255,0.04)' }}
          >
            <div className="px-4 py-2 flex items-center justify-between" style={{ background: 'rgba(255,255,255,0.03)' }}>
              <div className="flex items-center gap-2">
                <motion.div
                  className="w-6 h-6 rounded-lg flex items-center justify-center text-white"
                  style={{ background: 'var(--gradient-accent)' }}
                  initial={{ scale: 0 }}
                  animate={{ scale: 1 }}
                  transition={{ type: 'spring', stiffness: 400, damping: 15 }}
                >
                  <span className="text-[10px] font-bold">{selectedIds.size}</span>
                </motion.div>
                <span className="text-xs font-medium" style={{ color: 'rgba(255,255,255,0.6)' }}>
                  Selected from <span className="font-bold text-white capitalize">{lockedSource}</span>
                </span>
              </div>
              <button
                onClick={() => { useAppStore.getState().deselectAll(); hapticFeedback('light'); }}
                className="text-xs font-semibold text-red-400 hover:text-red-300 transition-colors"
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
    <motion.button
      onClick={() => { onClick(); hapticFeedback('light'); }}
      className={`flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-semibold whitespace-nowrap transition-colors duration-200 ${
        active
          ? 'bg-white text-black'
          : 'text-white/50 hover:text-white/70'
      }`}
      style={{
        border: active ? 'none' : '1px solid rgba(255,255,255,0.06)',
        boxShadow: active ? '0 1px 6px rgba(255,255,255,0.08)' : 'none',
      }}
      whileTap={{ scale: 0.92 }}
    >
      {icon}
      {label}
    </motion.button>
  );
}
