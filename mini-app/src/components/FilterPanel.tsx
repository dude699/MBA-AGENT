// ============================================================
// FILTER PANEL — v4.0: Zero-glitch mobile-first filter sheet
// ============================================================
// Root fixes:
//   1. Removed framer-motion AnimatePresence animations that caused
//      mobile WebView reflow glitches (white flash, double-render)
//   2. Replaced motion.div sections with CSS transitions (GPU-accelerated)
//   3. Fixed touch scroll propagation — panel scrolls independently
//   4. Fixed backdrop click area — no more phantom triggers
//   5. Removed height:0 animation on sections (cause of filter glitch)
//   6. All event handlers use stopPropagation + preventDefault correctly
// ============================================================

import React, { useState, useRef, useCallback, useEffect } from 'react';
import {
  X, RotateCcw, ChevronDown, ChevronUp, Check,
  MapPin, Clock, Briefcase, DollarSign, Shield, Star,
  Building2, Tag, Calendar, Layers,
} from 'lucide-react';
import { useAppStore } from '@/store/useAppStore';
import { hapticFeedback } from '@/utils/helpers';
import {
  CATEGORIES, LOCATIONS, POPULAR_SKILLS, SECTORS,
  SOURCE_CONFIG, POSTED_WITHIN_OPTIONS, STIPEND_RANGES,
  TIER_LABELS,
} from '@/utils/constants';
import { SourceIcon, TierIcon } from '@/components/SourceIcons';
import type { InternshipSource, CompanyTier } from '@/types';

export default function FilterPanel() {
  const { isFilterOpen, setFilterOpen, filters, setFilters, resetFilters, activeFilterCount } = useAppStore();
  const [expandedSections, setExpandedSections] = useState<Set<string>>(new Set(['source', 'stipend', 'duration']));
  const scrollRef = useRef<HTMLDivElement>(null);
  const [isVisible, setIsVisible] = useState(false);

  // Two-phase visibility: mount -> animate in
  useEffect(() => {
    if (isFilterOpen) {
      // Force layout before starting animation
      requestAnimationFrame(() => {
        setIsVisible(true);
      });
    } else {
      setIsVisible(false);
    }
  }, [isFilterOpen]);

  const toggleSection = useCallback((key: string) => {
    setExpandedSections((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
    hapticFeedback('light');
  }, []);

  const handleClose = useCallback(() => {
    setIsVisible(false);
    // Delay unmount so CSS transition plays
    setTimeout(() => setFilterOpen(false), 250);
  }, [setFilterOpen]);

  const handleBackdropClick = useCallback((e: React.MouseEvent) => {
    // Only close if clicking the backdrop itself, not children
    if (e.target === e.currentTarget) {
      e.preventDefault();
      e.stopPropagation();
      handleClose();
    }
  }, [handleClose]);

  // Block body scroll when filter is open
  useEffect(() => {
    if (isFilterOpen) {
      document.body.style.overflow = 'hidden';
      document.body.style.touchAction = 'none';
    }
    return () => {
      document.body.style.overflow = '';
      document.body.style.touchAction = '';
    };
  }, [isFilterOpen]);

  if (!isFilterOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50"
      style={{
        backgroundColor: isVisible ? 'rgba(0,0,0,0.2)' : 'rgba(0,0,0,0)',
        transition: 'background-color 0.25s ease',
        // No backdrop-blur — it causes rendering lag on mobile
      }}
      onClick={handleBackdropClick}
      // Prevent scroll-through to body
      onTouchMove={(e) => {
        // Allow scroll ONLY inside the scroll area
        if (scrollRef.current && scrollRef.current.contains(e.target as Node)) {
          // let it scroll naturally
        } else {
          e.preventDefault();
        }
      }}
    >
      <div
        style={{
          position: 'absolute',
          bottom: 0,
          left: 0,
          right: 0,
          maxHeight: '85vh',
          background: '#ffffff',
          borderRadius: '24px 24px 0 0',
          boxShadow: '0 -8px 40px rgba(0,0,0,0.08)',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
          transform: isVisible ? 'translateY(0)' : 'translateY(100%)',
          transition: 'transform 0.3s cubic-bezier(0.22, 1, 0.36, 1)',
          willChange: 'transform',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Handle */}
        <div className="flex justify-center pt-3 pb-1 flex-shrink-0">
          <div className="w-10 h-1 bg-gray-200 rounded-full" />
        </div>

        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3 flex-shrink-0" style={{ borderBottom: '1px solid rgba(0,0,0,0.05)' }}>
          <div className="flex items-center gap-2.5">
            <h2 className="text-base font-bold text-gray-900 tracking-tight">Filters</h2>
            {activeFilterCount > 0 && (
              <span className="text-white text-[10px] font-bold px-2 py-0.5 rounded-full min-w-[20px] text-center"
                style={{ background: 'linear-gradient(135deg, #0a0a0a 0%, #374151 100%)' }}>
                {activeFilterCount}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={(e) => { e.stopPropagation(); resetFilters(); hapticFeedback('medium'); }}
              className="flex items-center gap-1 text-xs font-semibold text-red-500 active:opacity-70"
            >
              <RotateCcw className="w-3.5 h-3.5" /> Reset
            </button>
            <button onClick={(e) => { e.stopPropagation(); handleClose(); }} className="p-1">
              <X className="w-5 h-5 text-gray-400" />
            </button>
          </div>
        </div>

        {/* Scrollable Filters — mobile-safe touch scrolling */}
        <div
          ref={scrollRef}
          className="flex-1 overflow-y-auto overscroll-contain"
          style={{
            WebkitOverflowScrolling: 'touch',
            touchAction: 'pan-y',
            overscrollBehavior: 'contain',
          }}
        >
          {/* SOURCE FILTER */}
          <FilterSection
            title="Source Platform"
            icon={<Layers className="w-4 h-4" />}
            expanded={expandedSections.has('source')}
            onToggle={() => toggleSection('source')}
            count={filters.sources.length}
          >
            <div className="grid grid-cols-2 gap-2">
              {(Object.keys(SOURCE_CONFIG) as InternshipSource[]).map((source) => {
                const config = SOURCE_CONFIG[source];
                const active = filters.sources.includes(source);
                return (
                  <button
                    key={source}
                    onClick={(e) => {
                      e.stopPropagation();
                      const next = active
                        ? filters.sources.filter((s) => s !== source)
                        : [...filters.sources, source];
                      setFilters({ sources: next });
                      hapticFeedback('light');
                    }}
                    className={`flex items-center gap-2 px-3 py-2.5 rounded-xl text-xs font-medium transition-colors duration-150 ${
                      active
                        ? 'text-white shadow-sm'
                        : 'bg-white text-gray-700 border border-gray-200 active:bg-gray-50'
                    }`}
                    style={active ? { background: config.color, borderColor: config.color } : {}}
                  >
                    <SourceIcon source={source} size={14} />
                    <span className="truncate">{config.name}</span>
                    {active && <Check className="w-3 h-3 ml-auto flex-shrink-0" />}
                  </button>
                );
              })}
            </div>
          </FilterSection>

          {/* STIPEND FILTER */}
          <FilterSection
            title="Stipend Range"
            icon={<DollarSign className="w-4 h-4" />}
            expanded={expandedSections.has('stipend')}
            onToggle={() => toggleSection('stipend')}
            count={filters.stipendMin > 0 || filters.stipendMax < 100000 ? 1 : 0}
          >
            <div className="space-y-3">
              <div className="flex items-center gap-3">
                <div className="flex-1">
                  <label className="text-[10px] font-semibold text-gray-400 uppercase mb-1 block tracking-wider">Min</label>
                  <input
                    type="range" min={0} max={100000} step={5000}
                    value={filters.stipendMin}
                    onChange={(e) => setFilters({ stipendMin: Number(e.target.value) })}
                    className="w-full accent-gray-900"
                  />
                  <span className="text-xs font-bold text-gray-800">INR {(filters.stipendMin / 1000).toFixed(0)}K</span>
                </div>
                <div className="flex-1">
                  <label className="text-[10px] font-semibold text-gray-400 uppercase mb-1 block tracking-wider">Max</label>
                  <input
                    type="range" min={0} max={100000} step={5000}
                    value={filters.stipendMax}
                    onChange={(e) => setFilters({ stipendMax: Number(e.target.value) })}
                    className="w-full accent-gray-900"
                  />
                  <span className="text-xs font-bold text-gray-800">INR {(filters.stipendMax / 1000).toFixed(0)}K</span>
                </div>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {STIPEND_RANGES.map((range) => (
                  <button
                    key={range.label}
                    onClick={(e) => {
                      e.stopPropagation();
                      setFilters({ stipendMin: range.min, stipendMax: range.max });
                      hapticFeedback('light');
                    }}
                    className={`text-[10px] font-semibold px-2.5 py-1 rounded-lg transition-colors duration-150 ${
                      filters.stipendMin === range.min && filters.stipendMax === range.max
                        ? 'text-white shadow-sm'
                        : 'bg-white text-gray-600 border border-gray-200'
                    }`}
                    style={
                      filters.stipendMin === range.min && filters.stipendMax === range.max
                        ? { background: 'linear-gradient(135deg, #0a0a0a 0%, #374151 100%)' } : {}
                    }
                  >
                    {range.label}
                  </button>
                ))}
              </div>
            </div>
          </FilterSection>

          {/* DURATION FILTER */}
          <FilterSection
            title="Duration"
            icon={<Clock className="w-4 h-4" />}
            expanded={expandedSections.has('duration')}
            onToggle={() => toggleSection('duration')}
            count={(filters.durationMax || 12) < 12 ? 1 : 0}
          >
            <div className="space-y-2">
              <input
                type="range" min={1} max={12}
                value={filters.durationMax}
                onChange={(e) => setFilters({ durationMax: Number(e.target.value) })}
                className="w-full accent-gray-900"
              />
              <div className="flex justify-between text-xs text-gray-500">
                <span>1 month</span>
                <span className="font-bold text-gray-900">{filters.durationMax} months max</span>
                <span>12 months</span>
              </div>
              <div className="flex gap-2">
                {[1, 2, 3, 6].map((m) => (
                  <button
                    key={m}
                    onClick={(e) => { e.stopPropagation(); setFilters({ durationMax: m }); hapticFeedback('light'); }}
                    className={`flex-1 py-1.5 rounded-lg text-xs font-semibold transition-colors duration-150 ${
                      filters.durationMax === m
                        ? 'text-white shadow-sm'
                        : 'bg-white text-gray-600 border border-gray-200'
                    }`}
                    style={filters.durationMax === m ? { background: 'linear-gradient(135deg, #0a0a0a 0%, #374151 100%)' } : {}}
                  >
                    {m}mo
                  </button>
                ))}
              </div>
            </div>
          </FilterSection>

          {/* CATEGORY FILTER */}
          <FilterSection
            title="Category"
            icon={<Briefcase className="w-4 h-4" />}
            expanded={expandedSections.has('category')}
            onToggle={() => toggleSection('category')}
            count={filters.categories.length}
          >
            <ChipGrid
              items={CATEGORIES}
              selected={filters.categories}
              onChange={(categories) => setFilters({ categories })}
            />
          </FilterSection>

          {/* LOCATION FILTER */}
          <FilterSection
            title="Location"
            icon={<MapPin className="w-4 h-4" />}
            expanded={expandedSections.has('location')}
            onToggle={() => toggleSection('location')}
            count={filters.locations.length + filters.locationTypes.length}
          >
            <div className="space-y-3">
              <div className="flex gap-2">
                {(['remote', 'onsite', 'hybrid'] as const).map((type) => (
                  <button
                    key={type}
                    onClick={(e) => {
                      e.stopPropagation();
                      const next = filters.locationTypes.includes(type)
                        ? filters.locationTypes.filter((t) => t !== type)
                        : [...filters.locationTypes, type];
                      setFilters({ locationTypes: next });
                      hapticFeedback('light');
                    }}
                    className={`flex-1 py-2 rounded-xl text-xs font-semibold capitalize transition-colors duration-150 ${
                      filters.locationTypes.includes(type)
                        ? 'text-white shadow-sm'
                        : 'bg-white text-gray-600 border border-gray-200'
                    }`}
                    style={filters.locationTypes.includes(type) ? { background: 'linear-gradient(135deg, #0a0a0a 0%, #374151 100%)' } : {}}
                  >
                    {type}
                  </button>
                ))}
              </div>
              <ChipGrid
                items={LOCATIONS}
                selected={filters.locations}
                onChange={(locations) => setFilters({ locations })}
              />
            </div>
          </FilterSection>

          {/* SKILLS FILTER */}
          <FilterSection
            title="Skills"
            icon={<Tag className="w-4 h-4" />}
            expanded={expandedSections.has('skills')}
            onToggle={() => toggleSection('skills')}
            count={filters.skills.length}
          >
            <ChipGrid
              items={POPULAR_SKILLS}
              selected={filters.skills}
              onChange={(skills) => setFilters({ skills })}
            />
          </FilterSection>

          {/* COMPANY TIER FILTER */}
          <FilterSection
            title="Company Tier"
            icon={<Building2 className="w-4 h-4" />}
            expanded={expandedSections.has('tier')}
            onToggle={() => toggleSection('tier')}
            count={filters.companyTiers.length}
          >
            <div className="grid grid-cols-2 gap-2">
              {(Object.entries(TIER_LABELS)).map(([key, config]) => {
                const active = filters.companyTiers.includes(key as CompanyTier);
                return (
                  <button
                    key={key}
                    onClick={(e) => {
                      e.stopPropagation();
                      const next = active
                        ? filters.companyTiers.filter((t) => t !== key)
                        : [...filters.companyTiers, key as CompanyTier];
                      setFilters({ companyTiers: next });
                      hapticFeedback('light');
                    }}
                    className={`flex items-center gap-2 px-3 py-2.5 rounded-xl text-xs font-medium transition-colors duration-150 ${
                      active
                        ? 'text-white border shadow-sm'
                        : 'bg-white text-gray-700 border border-gray-200'
                    }`}
                    style={active ? { backgroundColor: config.color, borderColor: config.color } : {}}
                  >
                    <TierIcon tier={key} size={14} />
                    <span>{config.label}</span>
                  </button>
                );
              })}
            </div>
          </FilterSection>

          {/* SECTOR FILTER */}
          <FilterSection
            title="Sector"
            icon={<Layers className="w-4 h-4" />}
            expanded={expandedSections.has('sector')}
            onToggle={() => toggleSection('sector')}
            count={filters.sectors.length}
          >
            <ChipGrid
              items={SECTORS}
              selected={filters.sectors}
              onChange={(sectors) => setFilters({ sectors })}
            />
          </FilterSection>

          {/* POSTED WITHIN */}
          <FilterSection
            title="Posted Within"
            icon={<Calendar className="w-4 h-4" />}
            expanded={expandedSections.has('posted')}
            onToggle={() => toggleSection('posted')}
            count={filters.postedWithin !== 'any' ? 1 : 0}
          >
            <div className="flex flex-wrap gap-2">
              {POSTED_WITHIN_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  onClick={(e) => { e.stopPropagation(); setFilters({ postedWithin: opt.value as any }); hapticFeedback('light'); }}
                  className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors duration-150 ${
                    filters.postedWithin === opt.value
                      ? 'text-white shadow-sm'
                      : 'bg-white text-gray-600 border border-gray-200'
                  }`}
                  style={filters.postedWithin === opt.value ? { background: 'linear-gradient(135deg, #0a0a0a 0%, #374151 100%)' } : {}}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </FilterSection>

          {/* ADVANCED FILTERS */}
          <FilterSection
            title="Advanced"
            icon={<Star className="w-4 h-4" />}
            expanded={expandedSections.has('advanced')}
            onToggle={() => toggleSection('advanced')}
            count={
              (filters.minMatchScore > 0 ? 1 : 0) +
              (filters.maxGhostScore < 100 ? 1 : 0) +
              (filters.successRateMin > 0 ? 1 : 0) +
              (filters.onlyVerified ? 1 : 0) +
              (filters.onlyPremium ? 1 : 0)
            }
          >
            <div className="space-y-4">
              <div>
                <div className="flex justify-between mb-1">
                  <label className="text-xs font-medium text-gray-600">Min Match Score</label>
                  <span className="text-xs font-bold text-gray-900">{filters.minMatchScore}%</span>
                </div>
                <input
                  type="range" min={0} max={100} step={5}
                  value={filters.minMatchScore}
                  onChange={(e) => setFilters({ minMatchScore: Number(e.target.value) })}
                  className="w-full accent-gray-900"
                />
              </div>

              <div>
                <div className="flex justify-between mb-1">
                  <label className="text-xs font-medium text-gray-600">Max Ghost Score</label>
                  <span className="text-xs font-bold text-amber-600">{filters.maxGhostScore}%</span>
                </div>
                <input
                  type="range" min={0} max={100} step={5}
                  value={filters.maxGhostScore}
                  onChange={(e) => setFilters({ maxGhostScore: Number(e.target.value) })}
                  className="w-full accent-amber-500"
                />
              </div>

              <div>
                <div className="flex justify-between mb-1">
                  <label className="text-xs font-medium text-gray-600">Min Success Rate</label>
                  <span className="text-xs font-bold text-emerald-600">{filters.successRateMin}%</span>
                </div>
                <input
                  type="range" min={0} max={100} step={5}
                  value={filters.successRateMin}
                  onChange={(e) => setFilters({ successRateMin: Number(e.target.value) })}
                  className="w-full accent-emerald-500"
                />
              </div>

              <div className="space-y-2">
                <ToggleSwitch
                  label="Only Verified Listings"
                  checked={filters.onlyVerified}
                  onChange={(v) => setFilters({ onlyVerified: v })}
                />
                <ToggleSwitch
                  label="Only Premium Listings"
                  checked={filters.onlyPremium}
                  onChange={(v) => setFilters({ onlyPremium: v })}
                />
                <ToggleSwitch
                  label="Hide Already Applied"
                  checked={filters.hideApplied}
                  onChange={(v) => setFilters({ hideApplied: v })}
                />
                <ToggleSwitch
                  label="Only With Stipend"
                  checked={filters.onlyWithStipend}
                  onChange={(v) => setFilters({ onlyWithStipend: v })}
                />
              </div>
            </div>
          </FilterSection>
        </div>

        {/* Apply Button — sticky at bottom, not absolute */}
        <div className="flex-shrink-0 p-4 border-t border-gray-100" style={{
          background: '#ffffff',
          paddingBottom: 'calc(1rem + env(safe-area-inset-bottom, 0px))',
        }}>
          <button
            onClick={(e) => { e.stopPropagation(); handleClose(); hapticFeedback('medium'); }}
            className="btn-primary w-full text-sm"
          >
            Apply Filters {activeFilterCount > 0 ? `(${activeFilterCount})` : ''}
          </button>
        </div>
      </div>
    </div>
  );
}

// ===== FILTER SECTION COMPONENT =====
function FilterSection({
  title, icon, expanded, onToggle, count, children,
}: {
  title: string;
  icon: React.ReactNode;
  expanded: boolean;
  onToggle: () => void;
  count: number;
  children: React.ReactNode;
}) {
  return (
    <div style={{ borderBottom: '1px solid rgba(0,0,0,0.04)' }}>
      <button
        onClick={(e) => { e.stopPropagation(); onToggle(); }}
        className="flex items-center justify-between w-full px-5 py-3.5 active:bg-gray-50 transition-colors"
        type="button"
      >
        <div className="flex items-center gap-2">
          <span className="text-gray-400">{icon}</span>
          <span className="text-sm font-semibold text-gray-800">{title}</span>
          {count > 0 && (
            <span className="text-white text-[9px] font-bold px-1.5 py-0.5 rounded-full min-w-[16px] text-center"
              style={{ background: 'linear-gradient(135deg, #0a0a0a 0%, #374151 100%)' }}>
              {count}
            </span>
          )}
        </div>
        {expanded ? <ChevronUp className="w-4 h-4 text-gray-300" /> : <ChevronDown className="w-4 h-4 text-gray-300" />}
      </button>
      {/* CSS transition instead of framer-motion — no glitch */}
      <div
        style={{
          display: 'grid',
          gridTemplateRows: expanded ? '1fr' : '0fr',
          opacity: expanded ? 1 : 0,
          transition: 'grid-template-rows 0.3s cubic-bezier(0.22, 1, 0.36, 1), opacity 0.25s ease',
        }}
      >
        <div style={{ overflow: 'hidden' }}>
          <div className="px-5 pb-4" onClick={(e) => e.stopPropagation()}>{children}</div>
        </div>
      </div>
    </div>
  );
}

// ===== CHIP GRID =====
function ChipGrid({
  items, selected, onChange,
}: {
  items: string[];
  selected: string[];
  onChange: (selected: string[]) => void;
}) {
  return (
    <div className="flex flex-wrap gap-1.5" onClick={(e) => e.stopPropagation()}>
      {items.map((item) => {
        const active = selected.includes(item);
        return (
          <button
            key={item}
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              const next = active
                ? selected.filter((s) => s !== item)
                : [...selected, item];
              onChange(next);
              hapticFeedback('light');
            }}
            className={`px-2.5 py-1 rounded-lg text-[11px] font-medium transition-colors duration-150 ${
              active
                ? 'text-white shadow-sm'
                : 'bg-white text-gray-600 border border-gray-200 active:bg-gray-50'
            }`}
            style={active ? { background: 'linear-gradient(135deg, #0a0a0a 0%, #374151 100%)' } : {}}
          >
            {item}
          </button>
        );
      })}
    </div>
  );
}

// ===== TOGGLE SWITCH =====
function ToggleSwitch({
  label, checked, onChange,
}: {
  label: string; checked: boolean; onChange: (v: boolean) => void;
}) {
  return (
    <button
      onClick={(e) => { e.stopPropagation(); onChange(!checked); hapticFeedback('light'); }}
      className="flex items-center justify-between w-full py-1"
      type="button"
    >
      <span className="text-xs font-medium text-gray-700">{label}</span>
      <div
        className="w-9 h-5 rounded-full relative"
        style={{
          background: checked ? '#0a0a0a' : '#e5e7eb',
          transition: 'background 0.2s ease',
        }}
      >
        <div
          className="absolute top-0.5 w-4 h-4 rounded-full bg-white shadow-sm"
          style={{
            transform: checked ? 'translateX(16px)' : 'translateX(2px)',
            transition: 'transform 0.2s ease',
          }}
        />
      </div>
    </button>
  );
}
