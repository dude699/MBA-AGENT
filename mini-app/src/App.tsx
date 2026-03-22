// ============================================================
// APP — Main Application Component
// ============================================================

import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { RefreshCw, ChevronUp, Clock, Archive, Database } from 'lucide-react';

import Header from '@/components/Header';
import InternshipCard from '@/components/InternshipCard';
import FilterPanel from '@/components/FilterPanel';
import SortPanel from '@/components/SortPanel';
import BatchApplyPanel from '@/components/BatchApplyPanel';
import LLMPanel from '@/components/LLMPanel';
import InternshipDetail from '@/components/InternshipDetail';
import AnalyticsDashboard from '@/components/AnalyticsDashboard';
import BottomBar from '@/components/BottomBar';
import SettingsPage from '@/components/SettingsPage';
import { ListSkeleton } from '@/components/Skeletons';
import { SourceIcon } from '@/components/SourceIcons';

import { useInternships, useFilteredInternships, useInfiniteScroll } from '@/hooks/useHooks';
import { useAppStore } from '@/store/useAppStore';
import { hapticFeedback } from '@/utils/helpers';
import { applyFilters, applySorting } from '@/utils/helpers';
import { SOURCE_CONFIG } from '@/utils/constants';
import { fetchSupabaseLatestJobs, fetchSupabaseAllJobs } from '@/services/api';
import type { Internship, InternshipSource } from '@/types';

export default function App() {
  const [activeTab, setActiveTab] = useState('browse');
  const [browseMode, setBrowseMode] = useState<'live' | 'latest' | 'archive'>('live');
  const [showScrollTop, setShowScrollTop] = useState(false);

  // Supabase state
  const [sbJobs, setSbJobs] = useState<Internship[]>([]);
  const [sbLoading, setSbLoading] = useState(false);
  const [sbPage, setSbPage] = useState(1);
  const [sbTotal, setSbTotal] = useState(0);
  const [sbHasMore, setSbHasMore] = useState(false);

  // Keep a window-level cache of Supabase jobs so InternshipDetail can find them
  useEffect(() => {
    (window as any).__sbJobsCache = sbJobs;
  }, [sbJobs]);

  const {
    isLoading, hasMore, totalCount, selectedIds, lockedSource,
    filters, sort, selectBySource, deselectAll,
  } = useAppStore();

  // Apply client-side filters + sort to supabase jobs for consistency
  const filteredSbJobs = useMemo(() => {
    if (sbJobs.length === 0) return [];
    let result = applyFilters(sbJobs, filters);
    result = applySorting(result, sort);
    return result;
  }, [sbJobs, filters, sort]);

  // Extra bottom padding when floating apply button is visible
  const hasSelection = selectedIds.size > 0;

  const { loadMore, isLoading: queryLoading, isFetchingNextPage, refetch } = useInternships();
  const filteredInternships = useFilteredInternships();

  // Infinite scroll sentinel
  const sentinelRef = useInfiniteScroll(loadMore, hasMore);

  // Scroll to top button — listen on both window and document for Telegram WebApp compatibility
  useEffect(() => {
    const handleScroll = () => {
      const scrollY = window.scrollY || document.documentElement.scrollTop || document.body.scrollTop || 0;
      setShowScrollTop(scrollY > 400);
    };
    window.addEventListener('scroll', handleScroll, { passive: true });
    document.addEventListener('scroll', handleScroll, { passive: true });
    return () => {
      window.removeEventListener('scroll', handleScroll);
      document.removeEventListener('scroll', handleScroll);
    };
  }, []);

  const scrollToTop = () => {
    window.scrollTo({ top: 0, behavior: 'smooth' });
    document.documentElement.scrollTop = 0;
    document.body.scrollTop = 0;
    hapticFeedback('light');
  };

  // Supabase data fetcher — now uses ALL active filters
  const loadSupabaseJobs = useCallback(async (mode: 'latest' | 'archive', page: number = 1) => {
    setSbLoading(true);
    try {
      const fetcher = mode === 'latest' ? fetchSupabaseLatestJobs : fetchSupabaseAllJobs;
      // Pass ALL current filters to Supabase queries
      const filterParams: any = {
        sources: filters.sources || [],
        categories: filters.categories || [],
        locations: filters.locations || [],
        search: filters.search || '',
        onlyWithStipend: filters.onlyWithStipend,
        durationMax: filters.durationMax,
      };

      const resp = await fetcher(page, 20, filterParams);
      if (page === 1) {
        setSbJobs(resp.data);
      } else {
        setSbJobs(prev => [...prev, ...resp.data]);
      }
      setSbTotal(resp.meta?.total || 0);
      setSbHasMore(resp.meta?.hasMore || false);
      setSbPage(page);
    } catch (err) {
      console.error('Supabase fetch error:', err);
    } finally {
      setSbLoading(false);
    }
  }, [filters]);

  // Load Supabase data when mode or filters change (react to all filter changes)
  useEffect(() => {
    if (browseMode !== 'live' && activeTab === 'browse') {
      setSbJobs([]);
      setSbPage(1);
      loadSupabaseJobs(browseMode === 'latest' ? 'latest' : 'archive', 1);
    }
  }, [browseMode, activeTab, loadSupabaseJobs]);

  return (
    <div className="app-root" style={{ background: '#ffffff', color: '#0a0a0a', minHeight: '100vh', touchAction: 'pan-y pan-x' }}>
      {/* Header with Search + Filters */}
      <Header />

      {/* Main Content */}
      <main>
        <AnimatePresence mode="wait">
          {activeTab === 'browse' && (
            <motion.div
              key="browse"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.15 }}
            >
              {/* Browse Mode Tabs: Live | Latest (Supabase) | Archive (Supabase) */}
              <div className="px-4 pt-3 pb-1">
                <div className="flex gap-1 rounded-xl p-1" style={{ background: '#f3f4f6' }}>
                  <button
                    onClick={() => { setBrowseMode('live'); hapticFeedback('light'); }}
                    className={`flex-1 flex items-center justify-center gap-1.5 py-2 rounded-lg text-[11px] font-bold transition-all ${
                      browseMode === 'live'
                        ? 'bg-white text-[#0a0a0a] shadow-sm'
                        : 'text-[#9ca3af]'
                    }`}
                  >
                    <RefreshCw className="w-3 h-3" />
                    Live
                  </button>
                  <button
                    onClick={() => { setBrowseMode('latest'); hapticFeedback('light'); }}
                    className={`flex-1 flex items-center justify-center gap-1.5 py-2 rounded-lg text-[11px] font-bold transition-all ${
                      browseMode === 'latest'
                        ? 'bg-white text-[#0a0a0a] shadow-sm'
                        : 'text-[#9ca3af]'
                    }`}
                  >
                    <Clock className="w-3 h-3" />
                    Latest
                  </button>
                  <button
                    onClick={() => { setBrowseMode('archive'); hapticFeedback('light'); }}
                    className={`flex-1 flex items-center justify-center gap-1.5 py-2 rounded-lg text-[11px] font-bold transition-all ${
                      browseMode === 'archive'
                        ? 'bg-white text-[#0a0a0a] shadow-sm'
                        : 'text-[#9ca3af]'
                    }`}
                  >
                    <Archive className="w-3 h-3" />
                    All Jobs
                  </button>
                </div>
              </div>

              {/* === LIVE MODE (original SQLite-based browse) === */}
              {browseMode === 'live' && (
                <>
                  {/* Source Quick Select Bar */}
                  <div className="px-4 pt-3 pb-1">
                    <div className="flex items-center gap-2 overflow-x-auto scrollbar-none pb-2">
                      <button
                        onClick={() => { deselectAll(); hapticFeedback('light'); }}
                        className={`flex-shrink-0 px-3 py-1.5 rounded-lg text-[11px] font-semibold transition-all whitespace-nowrap ${
                          !lockedSource
                            ? 'text-white shadow-sm'
                            : 'bg-white text-primary-600 border border-primary-200/60'
                        }`}
                        style={!lockedSource ? { background: 'var(--gradient-accent)' } : {}}
                      >
                        All Sources
                      </button>
                      {(Object.entries(SOURCE_CONFIG) as [string, typeof SOURCE_CONFIG[string]][]).slice(0, 16).map(([source, config]) => {
                        const count = filteredInternships.filter((i) => i.source === source).length;
                        if (count === 0) return null;
                        return (
                          <button
                            key={source}
                            onClick={() => {
                              if (lockedSource === source) {
                                deselectAll();
                              } else {
                                selectBySource(source as InternshipSource);
                              }
                              hapticFeedback('light');
                            }}
                            className={`flex-shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-semibold transition-all whitespace-nowrap ${
                              lockedSource === source
                                ? 'text-white shadow-sm'
                                : 'bg-white text-primary-600 border border-primary-200/60 hover:border-primary-300'
                            }`}
                            style={lockedSource === source ? { backgroundColor: config.color } : {}}
                          >
                            <SourceIcon source={source} size={12} /> {config.name}
                            <span className="opacity-70">({count})</span>
                          </button>
                        );
                      })}
                    </div>
                  </div>

                  {/* Results Count */}
                  <div className="px-5 py-2 flex items-center justify-between">
                    <p className="text-xs text-primary-500">
                      <span className="font-bold text-primary-800">{filteredInternships.length}</span> internships found
                      {filteredInternships.length !== totalCount && (
                        <span className="text-primary-400"> of {totalCount}</span>
                      )}
                    </p>
                    <button
                      onClick={() => { refetch(); hapticFeedback('light'); }}
                      className="flex items-center gap-1 text-[11px] font-medium text-primary-500 hover:text-accent transition-colors"
                    >
                      <RefreshCw className={`w-3 h-3 ${queryLoading ? 'animate-spin' : ''}`} />
                      Refresh
                    </button>
                  </div>

                  {/* Listings */}
                  <div className="px-4 space-y-3" style={{ paddingBottom: hasSelection ? '80px' : '16px' }}>
                    {queryLoading && !isFetchingNextPage ? (
                      <ListSkeleton count={5} />
                    ) : filteredInternships.length === 0 ? (
                      <EmptyState />
                    ) : (
                      <>
                        {filteredInternships.map((internship, index) => (
                          <InternshipCard
                            key={internship.id}
                            internship={internship}
                            index={index}
                          />
                        ))}

                        {/* Infinite scroll sentinel */}
                        {hasMore && (
                          <div ref={sentinelRef} className="py-4">
                            {isFetchingNextPage && (
                              <div className="flex justify-center">
                                <div className="flex items-center gap-2 text-xs text-primary-500">
                                  <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                                  Loading more...
                                </div>
                              </div>
                            )}
                          </div>
                        )}

                        {!hasMore && filteredInternships.length > 0 && (
                          <div className="py-6 text-center">
                            <p className="text-xs text-primary-400">
                              You've seen all {filteredInternships.length} internships
                            </p>
                          </div>
                        )}
                      </>
                    )}
                  </div>
                </>
              )}

              {/* === SUPABASE MODE (Latest or Archive) === */}
              {browseMode !== 'live' && (
                <div className="px-4">
                  <div className="py-2 flex items-center justify-between">
                    <p className="text-xs text-primary-500">
                      <Database className="w-3 h-3 inline mr-1" />
                      <span className="font-bold text-primary-800">{filteredSbJobs.length}</span>
                      {' '}{browseMode === 'latest' ? 'latest session' : 'archived'} jobs
                      {filteredSbJobs.length !== sbTotal && (
                        <span className="text-primary-400"> of {sbTotal}</span>
                      )}
                    </p>
                    <button
                      onClick={() => { loadSupabaseJobs(browseMode === 'latest' ? 'latest' : 'archive', 1); hapticFeedback('light'); }}
                      className="flex items-center gap-1 text-[11px] font-medium text-primary-500 hover:text-accent transition-colors"
                    >
                      <RefreshCw className={`w-3 h-3 ${sbLoading ? 'animate-spin' : ''}`} />
                      Refresh
                    </button>
                  </div>

                  <div className="space-y-3" style={{ paddingBottom: hasSelection ? '80px' : '16px' }}>
                    {sbLoading && sbJobs.length === 0 ? (
                      <ListSkeleton count={5} />
                    ) : filteredSbJobs.length === 0 ? (
                      <div className="py-16 text-center">
                        <div className="w-20 h-20 rounded-3xl flex items-center justify-center mx-auto mb-4" style={{background:'#f3f4f6'}}>
                          <Clock className="w-8 h-8" style={{color:'#d1d5db'}} />
                        </div>
                        <h3 className="text-base font-bold mb-2" style={{color:'#1f2937'}}>
                          {sbJobs.length > 0 ? 'No Jobs Match Filters' : browseMode === 'latest' ? 'No Latest Jobs' : 'No Archived Jobs'}
                        </h3>
                        <p className="text-xs" style={{color:'#6b7280'}}>
                          {sbJobs.length > 0
                            ? 'Try adjusting your filters to see more results.'
                            : browseMode === 'latest'
                              ? 'Jobs from the current scraping session will appear here.'
                              : 'All previously scraped jobs will be archived here.'}
                        </p>
                        {sbJobs.length > 0 && (
                          <button
                            onClick={() => { useAppStore.getState().resetFilters(); hapticFeedback('medium'); }}
                            className="btn-primary text-xs mt-3"
                          >
                            Reset All Filters
                          </button>
                        )}
                      </div>
                    ) : (
                      <>
                        {filteredSbJobs.map((internship, index) => (
                          <InternshipCard
                            key={internship.id}
                            internship={internship}
                            index={index}
                          />
                        ))}

                        {sbHasMore && (
                          <div className="py-4">
                            <button
                              onClick={() => loadSupabaseJobs(browseMode === 'latest' ? 'latest' : 'archive', sbPage + 1)}
                              disabled={sbLoading}
                              className="w-full py-3 bg-surface-muted text-primary-600 rounded-xl text-xs font-semibold hover:bg-surface-border transition-colors"
                            >
                              {sbLoading ? (
                                <span className="flex items-center justify-center gap-2">
                                  <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                                  Loading...
                                </span>
                              ) : (
                                `Load More (${sbJobs.length} of ${sbTotal})`
                              )}
                            </button>
                          </div>
                        )}

                        {!sbHasMore && filteredSbJobs.length > 0 && (
                          <div className="py-6 text-center">
                            <p className="text-xs text-primary-400">
                              All {filteredSbJobs.length} jobs loaded
                            </p>
                          </div>
                        )}
                      </>
                    )}
                  </div>
                </div>
              )}
            </motion.div>
          )}

          {activeTab === 'analytics' && (
            <motion.div
              key="analytics"
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -20 }}
              transition={{ duration: 0.2 }}
            >
              <AnalyticsDashboard />
            </motion.div>
          )}

          {activeTab === 'settings' && (
            <motion.div
              key="settings"
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -20 }}
              transition={{ duration: 0.2 }}
            >
              <SettingsPage />
            </motion.div>
          )}
        </AnimatePresence>
      </main>

      {/* Panels & Modals — z-index: Filter/Sort 50, LLM 60, Detail 50 */}
      <FilterPanel />
      <SortPanel />
      <BatchApplyPanel />
      <LLMPanel />
      <InternshipDetail />

      {/* Bottom Navigation */}
      <BottomBar activeTab={activeTab} onTabChange={setActiveTab} />

      {/* Scroll to Top — stays above content but below bottom bar */}
      <AnimatePresence>
        {showScrollTop && (
          <motion.button
            initial={{ opacity: 0, scale: 0.8 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.8 }}
            onClick={scrollToTop}
            className="fixed right-4 z-30 w-10 h-10 rounded-full flex items-center justify-center transition-colors"
            style={{ background: '#ffffff', border: '1px solid #e5e7eb', boxShadow: '0 4px 24px rgba(0,0,0,0.08)', bottom: 'calc(88px + env(safe-area-inset-bottom, 0px))' }}
          >
            <ChevronUp className="w-5 h-5" style={{color:'#4b5563'}} />
          </motion.button>
        )}
      </AnimatePresence>
    </div>
  );
}

// ===== EMPTY STATE =====
function EmptyState() {
  const { resetFilters } = useAppStore();

  return (
    <div className="py-16 text-center px-8">
      <div className="w-20 h-20 rounded-3xl flex items-center justify-center mx-auto mb-4" style={{background:'#f3f4f6'}}>
        <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="#d1d5db" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="11" cy="11" r="8" />
          <path d="m21 21-4.35-4.35" />
        </svg>
      </div>
      <h3 className="text-base font-bold mb-2" style={{color:'#1f2937'}}>No internships found</h3>
      <p className="text-xs mb-4 leading-relaxed" style={{color:'#9ca3af'}}>
        Try adjusting your filters or search terms to discover more opportunities.
      </p>
      <button
        onClick={() => { resetFilters(); hapticFeedback('medium'); }}
        className="btn-primary text-xs"
      >
        Reset All Filters
      </button>
    </div>
  );
}
