// ============================================================
// HEADER — PRISM v0.2 Zero-Glitch Frosted Glass Header
// ------------------------------------------------------------
// Changes vs v0.1:
//   - Replaced every motion.* element with plain HTML.
//     framer-motion was used for whileTap / whileHover scales
//     and trivial AnimatePresence pop-ins, which forced the
//     entire header to re-render on every search keystroke.
//   - Tap feedback is now `active:scale-[0.95]` — instant,
//     GPU-cheap, and doesn't run a JS animation loop.
//   - Selection bar uses a CSS `transition: max-height` slide
//     instead of layout-animated height: auto (which can flash
//     a 1-frame full-height paint before settling).
// ============================================================

import React, { useState, useCallback, useRef, useEffect } from 'react';
import {
  Search, SlidersHorizontal, ArrowUpDown, Sparkles,
  X, Shield, Clock, Zap
} from 'lucide-react';
import { useAppStore } from '@/store/useAppStore';
import { hapticFeedback } from '@/utils/helpers';

export default function Header() {
  const {
    filters, activeFilterCount,
    isFilterOpen, isSortOpen, isLLMPanelOpen,
    setFilterOpen, setSortOpen, setLLMPanelOpen, setSearch,
    selectedIds, lockedSource,
  } = useAppStore();

  const [searchFocused, setSearchFocused] = useState(false);
  const [searchValue, setSearchValue] = useState(filters.search);
  const searchTimeoutRef = useRef<ReturnType<typeof setTimeout>>();

  const handleSearchChange = useCallback((value: string) => {
    setSearchValue(value);
    if (searchTimeoutRef.current) clearTimeout(searchTimeoutRef.current);
    searchTimeoutRef.current = setTimeout(() => setSearch(value), 250);
  }, [setSearch]);

  useEffect(() => () => {
    if (searchTimeoutRef.current) clearTimeout(searchTimeoutRef.current);
  }, []);

  const filterActive = isFilterOpen || activeFilterCount > 0;

  return (
    <header
      className="sticky z-40"
      style={{
        top: 'calc(env(safe-area-inset-top, 0px) + var(--tg-header-height, 0px))',
        background: 'rgba(5,5,8,0.97)',
        backdropFilter: 'blur(24px) saturate(180%)',
        WebkitBackdropFilter: 'blur(24px) saturate(180%)',
        borderBottom: '1px solid rgba(255,255,255,0.08)',
      }}
    >
      {/* Top Bar */}
      <div className="px-4 pt-3 pb-2">
        <div className="flex items-center justify-between mb-3">
          {/* Brand */}
          <div className="flex items-center gap-3">
            <div
              className="w-10 h-10 rounded-xl flex items-center justify-center relative overflow-hidden active:scale-[0.92] transition-transform"
              style={{
                background: 'linear-gradient(135deg, #ffffff 0%, #f0f0f0 100%)',
                boxShadow: '0 2px 12px rgba(255,255,255,0.15)',
                transitionDuration: '120ms',
              }}
            >
              <Zap className="w-5 h-5 text-black" strokeWidth={2.5} />
              <div
                aria-hidden="true"
                className="absolute inset-0 opacity-30"
                style={{
                  background: 'linear-gradient(135deg, transparent 40%, rgba(255,255,255,0.8) 50%, transparent 60%)',
                }}
              />
            </div>
            <div>
              <h1 className="text-[15px] font-bold leading-tight tracking-tight" style={{ color: '#ffffff' }}>
                InternHub Pro
              </h1>
              <div className="flex items-center gap-1.5">
                <span
                  className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-micro-pulse"
                  style={{ boxShadow: '0 0 6px rgba(52,211,153,0.5)' }}
                />
                <p className="text-[10px] font-medium tracking-wide" style={{ color: 'rgba(255,255,255,0.45)' }}>
                  PRISM Intelligence Active
                </p>
              </div>
            </div>
          </div>

          {/* AI Sparkles Button */}
          <button
            type="button"
            onClick={() => { setLLMPanelOpen(!isLLMPanelOpen); hapticFeedback('light'); }}
            aria-label="AI Chat"
            aria-pressed={isLLMPanelOpen}
            className="relative p-2.5 rounded-xl active:scale-[0.9] transition-all"
            style={{
              background: isLLMPanelOpen
                ? 'linear-gradient(135deg, #6366f1, #8b5cf6)'
                : 'rgba(255,255,255,0.06)',
              boxShadow: isLLMPanelOpen ? '0 4px 16px rgba(99,102,241,0.3)' : 'none',
              transitionDuration: '160ms',
            }}
          >
            <Sparkles
              className="w-[18px] h-[18px]"
              style={{ color: isLLMPanelOpen ? '#fff' : 'rgba(255,255,255,0.5)' }}
            />
            <span
              aria-hidden="true"
              className="absolute -top-0.5 -right-0.5 w-2.5 h-2.5 rounded-full border-2"
              style={{
                background: '#10b981',
                borderColor: 'rgba(5,5,8,0.95)',
                boxShadow: '0 0 6px rgba(16,185,129,0.4)',
              }}
            />
          </button>
        </div>

        {/* Search Bar */}
        <div
          className="relative rounded-xl overflow-hidden"
          style={{
            boxShadow: searchFocused
              ? '0 0 0 2px rgba(255,255,255,0.1), 0 4px 16px rgba(0,0,0,0.2)'
              : '0 0 0 1px rgba(255,255,255,0.06)',
            transition: 'box-shadow 200ms ease',
          }}
        >
          <Search
            className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4"
            style={{
              color: searchFocused ? 'rgba(255,255,255,0.6)' : 'rgba(255,255,255,0.25)',
              transition: 'color 160ms ease',
            }}
          />
          <input
            type="text"
            value={searchValue}
            onChange={(e) => handleSearchChange(e.target.value)}
            onFocus={() => setSearchFocused(true)}
            onBlur={() => setSearchFocused(false)}
            placeholder="Search companies, roles, skills..."
            aria-label="Search"
            className="w-full pl-10 pr-10 py-2.5 rounded-xl text-sm text-white placeholder-white/25 focus:outline-none"
            style={{
              background: searchFocused ? 'rgba(255,255,255,0.08)' : 'rgba(255,255,255,0.04)',
              transition: 'background 200ms ease',
            }}
          />
          {searchValue && (
            <button
              type="button"
              onClick={() => { handleSearchChange(''); hapticFeedback('light'); }}
              aria-label="Clear search"
              className="absolute right-3 top-1/2 -translate-y-1/2 p-1 rounded-full active:scale-90 transition-transform"
              style={{ background: 'rgba(255,255,255,0.1)', transitionDuration: '120ms' }}
            >
              <X className="w-3 h-3 text-white/60" />
            </button>
          )}
        </div>
      </div>

      {/* Action Bar */}
      <div className="px-4 pb-3 flex items-center gap-2 overflow-x-auto scrollbar-none">
        {/* Filter Button */}
        <button
          type="button"
          onClick={() => { setFilterOpen(!isFilterOpen); hapticFeedback('light'); }}
          aria-pressed={isFilterOpen}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold active:scale-95 ${
            filterActive ? 'bg-white text-black' : 'text-white/60'
          }`}
          style={{
            border: filterActive ? 'none' : '1px solid rgba(255,255,255,0.08)',
            boxShadow: filterActive ? '0 2px 8px rgba(255,255,255,0.1)' : 'none',
            transition: 'background 160ms ease, color 160ms ease, transform 100ms ease',
          }}
        >
          <SlidersHorizontal className="w-3.5 h-3.5" />
          <span>Filters</span>
          {activeFilterCount > 0 && (
            <span
              className="text-[10px] px-1.5 py-0.5 rounded-full font-bold min-w-[18px] text-center"
              style={{
                background: filterActive ? '#0a0a0a' : 'rgba(255,255,255,0.15)',
                color: '#fff',
              }}
            >
              {activeFilterCount}
            </span>
          )}
        </button>

        {/* Sort Button */}
        <button
          type="button"
          onClick={() => { setSortOpen(!isSortOpen); hapticFeedback('light'); }}
          aria-pressed={isSortOpen}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold text-white/60 active:scale-95"
          style={{
            border: '1px solid rgba(255,255,255,0.08)',
            transition: 'color 160ms ease, transform 100ms ease',
          }}
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
            label="INR Paid"
            icon={<span className="text-[10px] font-bold">₹</span>}
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

      {/* Selection Bar — CSS max-height slide, no layout animation */}
      <div
        className="overflow-hidden"
        style={{
          borderTop: selectedIds.size > 0 ? '1px solid rgba(255,255,255,0.04)' : 'none',
          maxHeight: selectedIds.size > 0 ? 56 : 0,
          opacity: selectedIds.size > 0 ? 1 : 0,
          transition: 'max-height 220ms cubic-bezier(0.22, 1, 0.36, 1), opacity 180ms ease',
        }}
        aria-hidden={selectedIds.size === 0}
      >
        <div
          className="px-4 py-2 flex items-center justify-between"
          style={{ background: 'rgba(255,255,255,0.03)' }}
        >
          <div className="flex items-center gap-2">
            <span
              className="w-6 h-6 rounded-lg flex items-center justify-center text-white"
              style={{ background: 'var(--gradient-accent)' }}
            >
              <span className="text-[10px] font-bold">{selectedIds.size}</span>
            </span>
            <span className="text-xs font-medium" style={{ color: 'rgba(255,255,255,0.6)' }}>
              Selected from <span className="font-bold text-white capitalize">{lockedSource}</span>
            </span>
          </div>
          <button
            type="button"
            onClick={() => { useAppStore.getState().deselectAll(); hapticFeedback('light'); }}
            className="text-xs font-semibold text-red-400 active:text-red-300"
          >
            Clear All
          </button>
        </div>
      </div>
    </header>
  );
}

// ===== QUICK CHIP COMPONENT =====
function QuickChip({
  label, icon, active, onClick,
}: {
  label: string; icon?: React.ReactNode; active: boolean; onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={() => { onClick(); hapticFeedback('light'); }}
      aria-pressed={active}
      className={`flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-semibold whitespace-nowrap active:scale-[0.92] ${
        active ? 'bg-white text-black' : 'text-white/50'
      }`}
      style={{
        border: active ? 'none' : '1px solid rgba(255,255,255,0.06)',
        boxShadow: active ? '0 1px 6px rgba(255,255,255,0.08)' : 'none',
        transition: 'background 160ms ease, color 160ms ease, transform 100ms ease',
      }}
    >
      {icon}
      {label}
    </button>
  );
}
