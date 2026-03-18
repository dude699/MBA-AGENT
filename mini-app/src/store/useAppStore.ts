// ============================================================
// INTERNSHIP HUB — ZUSTAND STORE (COMPLETE STATE MANAGEMENT)
// ============================================================

import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type {
  Internship, FilterState, SortField, BatchState,
  LLMMessage, AnalyticsData, SourceCredentials,
  UserPreferences, InternshipSource, ApplicationStatus,
} from '@/types';
import { DEFAULT_FILTERS, DEFAULT_SORT } from '@/utils/constants';
import { v4 as uuid } from 'uuid';

// ===== MAIN APP STORE =====
interface AppState {
  // Internships
  internships: Internship[];
  filteredInternships: Internship[];
  selectedIds: Set<string>;
  viewedIds: Set<string>;
  appliedIds: Set<string>;
  dismissedIds: Set<string>;

  // Filters & Sort
  filters: FilterState;
  sort: SortField;
  activeFilterCount: number;

  // Batch Apply
  batch: BatchState;
  lockedSource: InternshipSource | null;

  // LLM Chat
  llmMessages: LLMMessage[];
  llmLoading: boolean;

  // Analytics
  analytics: AnalyticsData | null;

  // Credentials
  credentials: SourceCredentials[];

  // Preferences
  preferences: UserPreferences;

  // UI State
  isLoading: boolean;
  isFilterOpen: boolean;
  isSortOpen: boolean;
  isBatchPanelOpen: boolean;
  isLLMPanelOpen: boolean;
  isDetailOpen: string | null;
  page: number;
  hasMore: boolean;
  totalCount: number;

  // Actions — Internships
  setInternships: (items: Internship[]) => void;
  appendInternships: (items: Internship[]) => void;
  removeInternship: (id: string) => void;
  markApplied: (id: string, status: ApplicationStatus) => void;
  dismissInternship: (id: string) => void;

  // Actions — Selection
  toggleSelect: (id: string) => void;
  selectAll: () => void;
  deselectAll: () => void;
  selectBySource: (source: InternshipSource) => void;

  // Actions — Filters
  setFilters: (filters: Partial<FilterState>) => void;
  resetFilters: () => void;
  setSort: (sort: SortField) => void;
  setSearch: (search: string) => void;

  // Actions — Batch
  setBatchState: (state: Partial<BatchState>) => void;
  startBatch: () => void;
  cancelBatch: () => void;
  completeBatch: () => void;
  setLockedSource: (source: InternshipSource | null) => void;

  // Actions — LLM
  addLLMMessage: (message: Omit<LLMMessage, 'id' | 'timestamp'>) => void;
  setLLMLoading: (loading: boolean) => void;
  clearLLMChat: () => void;

  // Actions — Credentials
  setCredentials: (cred: SourceCredentials) => void;
  removeCredentials: (source: InternshipSource) => void;

  // Actions — UI
  setLoading: (loading: boolean) => void;
  setFilterOpen: (open: boolean) => void;
  setSortOpen: (open: boolean) => void;
  setBatchPanelOpen: (open: boolean) => void;
  setLLMPanelOpen: (open: boolean) => void;
  setDetailOpen: (id: string | null) => void;
  setPage: (page: number) => void;
  setHasMore: (hasMore: boolean) => void;
  setTotalCount: (count: number) => void;
  setAnalytics: (data: AnalyticsData) => void;
}

function countActiveFilters(filters: FilterState): number {
  let count = 0;
  if (filters.search) count++;
  if (filters.sources.length > 0) count++;
  if (filters.categories.length > 0) count++;
  if (filters.locations.length > 0) count++;
  if (filters.locationTypes.length > 0) count++;
  if (filters.stipendMin > 0) count++;
  if (filters.stipendMax < 100000) count++;
  if (filters.stipendType.length > 0) count++;
  if (filters.durationMax < 3) count++;
  if (filters.skills.length > 0) count++;
  if (filters.companyTiers.length > 0) count++;
  if (filters.sectors.length > 0) count++;
  if (filters.minOpenings > 0) count++;
  if (filters.minMatchScore > 0) count++;
  if (filters.maxGhostScore < 100) count++;
  if (filters.onlyVerified) count++;
  if (filters.onlyPremium) count++;
  if (filters.postedWithin !== 'any') count++;
  if (filters.deadlineWithin !== 'any') count++;
  if (filters.successRateMin > 0) count++;
  if (filters.tags.length > 0) count++;
  return count;
}

export const useAppStore = create<AppState>()(
  persist(
    (set, get) => ({
      // Initial state
      internships: [],
      filteredInternships: [],
      selectedIds: new Set<string>(),
      viewedIds: new Set<string>(),
      appliedIds: new Set<string>(),
      dismissedIds: new Set<string>(),

      filters: DEFAULT_FILTERS,
      sort: DEFAULT_SORT,
      activeFilterCount: 0,

      batch: {
        id: '',
        status: 'idle',
        source: null,
        selectedIds: [],
        processedIds: [],
        failedIds: [],
        currentIndex: 0,
        totalCount: 0,
        errors: [],
        successCount: 0,
        failCount: 0,
      },
      lockedSource: null,

      llmMessages: [],
      llmLoading: false,

      analytics: null,

      credentials: [],

      preferences: {
        defaultSort: 'stipend_high',
        defaultFilters: {},
        autoApplyDefaults: {
          maxStipend: true,
          maxDuration: 3,
          preferredSources: ['internshala', 'unstop'],
          batchSize: 5,
        },
        notifications: {
          newListings: true,
          applicationUpdates: true,
          batchComplete: true,
          deadlineReminders: true,
        },
        theme: 'light',
        compactView: false,
      },

      isLoading: false,
      isFilterOpen: false,
      isSortOpen: false,
      isBatchPanelOpen: false,
      isLLMPanelOpen: false,
      isDetailOpen: null,
      page: 1,
      hasMore: true,
      totalCount: 0,

      // ===== INTERNSHIP ACTIONS =====
      setInternships: (items) => {
        const dismissed = get().dismissedIds;
        const applied = get().appliedIds;
        const filtered = items.filter(
          (i) => !dismissed.has(i.id) && !i.isExpired
        ).map((i) => ({
          ...i,
          alreadyApplied: applied.has(i.id) || i.alreadyApplied,
        }));
        set({ internships: filtered, filteredInternships: filtered });
      },

      appendInternships: (items) => {
        const dismissed = get().dismissedIds;
        const current = get().internships;
        const existingHashes = new Set(current.map((i) => i.hash));
        const newItems = items.filter(
          (i) => !dismissed.has(i.id) && !i.isExpired && !existingHashes.has(i.hash)
        );
        const all = [...current, ...newItems];
        set({ internships: all, filteredInternships: all });
      },

      removeInternship: (id) => {
        set((state) => ({
          internships: state.internships.filter((i) => i.id !== id),
          filteredInternships: state.filteredInternships.filter((i) => i.id !== id),
        }));
      },

      markApplied: (id, status) => {
        set((state) => {
          const newApplied = new Set(state.appliedIds);
          newApplied.add(id);
          return {
            appliedIds: newApplied,
            internships: state.internships.map((i) =>
              i.id === id ? { ...i, alreadyApplied: true, applicationStatus: status, appliedDate: new Date().toISOString() } : i
            ),
            filteredInternships: state.filteredInternships.map((i) =>
              i.id === id ? { ...i, alreadyApplied: true, applicationStatus: status, appliedDate: new Date().toISOString() } : i
            ),
          };
        });
      },

      dismissInternship: (id) => {
        set((state) => {
          const newDismissed = new Set(state.dismissedIds);
          newDismissed.add(id);
          return {
            dismissedIds: newDismissed,
            internships: state.internships.filter((i) => i.id !== id),
            filteredInternships: state.filteredInternships.filter((i) => i.id !== id),
          };
        });
      },

      // ===== SELECTION ACTIONS =====
      toggleSelect: (id) => {
        set((state) => {
          const newSelected = new Set(state.selectedIds);
          if (newSelected.has(id)) {
            newSelected.delete(id);
          } else {
            // Source locking: can only select from one source at a time
            const item = state.internships.find((i) => i.id === id);
            if (item && state.lockedSource && item.source !== state.lockedSource) {
              return state; // Don't add from different source
            }
            if (item && !state.lockedSource) {
              return { selectedIds: new Set([id]), lockedSource: item.source };
            }
            newSelected.add(id);
          }
          if (newSelected.size === 0) {
            return { selectedIds: newSelected, lockedSource: null };
          }
          return { selectedIds: newSelected };
        });
      },

      selectAll: () => {
        const state = get();
        const source = state.lockedSource;
        if (!source) return;
        const sourceItems = state.filteredInternships
          .filter((i) => i.source === source && !i.alreadyApplied && !i.isExpired)
          .slice(0, 50);
        set({ selectedIds: new Set(sourceItems.map((i) => i.id)) });
      },

      deselectAll: () => {
        set({ selectedIds: new Set(), lockedSource: null });
      },

      selectBySource: (source) => {
        const items = get().filteredInternships
          .filter((i) => i.source === source && !i.alreadyApplied && !i.isExpired)
          .slice(0, 50);
        set({
          selectedIds: new Set(items.map((i) => i.id)),
          lockedSource: source,
        });
      },

      // ===== FILTER ACTIONS =====
      setFilters: (newFilters) => {
        set((state) => {
          const updated = { ...state.filters, ...newFilters };
          return {
            filters: updated,
            activeFilterCount: countActiveFilters(updated),
          };
        });
      },

      resetFilters: () => {
        set({
          filters: DEFAULT_FILTERS,
          activeFilterCount: 0,
        });
      },

      setSort: (sort) => set({ sort }),

      setSearch: (search) => {
        set((state) => ({
          filters: { ...state.filters, search },
        }));
      },

      // ===== BATCH ACTIONS =====
      setBatchState: (newState) => {
        set((state) => ({
          batch: { ...state.batch, ...newState },
        }));
      },

      startBatch: () => {
        const state = get();
        set({
          batch: {
            ...state.batch,
            id: uuid(),
            status: 'running',
            selectedIds: Array.from(state.selectedIds),
            totalCount: state.selectedIds.size,
            startedAt: new Date().toISOString(),
            currentIndex: 0,
            processedIds: [],
            failedIds: [],
            errors: [],
            successCount: 0,
            failCount: 0,
          },
        });
      },

      cancelBatch: () => {
        set((state) => ({
          batch: { ...state.batch, status: 'paused' },
        }));
      },

      completeBatch: () => {
        const cooldownMinutes = 15;
        set((state) => ({
          batch: {
            ...state.batch,
            status: 'cooldown',
            completedAt: new Date().toISOString(),
            cooldownEndsAt: new Date(Date.now() + cooldownMinutes * 60000).toISOString(),
            nextBatchUnlocksAt: new Date(Date.now() + cooldownMinutes * 60000).toISOString(),
          },
          selectedIds: new Set(),
        }));
      },

      setLockedSource: (source) => set({ lockedSource: source }),

      // ===== LLM ACTIONS =====
      addLLMMessage: (message) => {
        set((state) => ({
          llmMessages: [
            ...state.llmMessages,
            { ...message, id: uuid(), timestamp: new Date().toISOString() },
          ],
        }));
      },

      setLLMLoading: (loading) => set({ llmLoading: loading }),

      clearLLMChat: () => set({ llmMessages: [] }),

      // ===== CREDENTIAL ACTIONS =====
      setCredentials: (cred) => {
        set((state) => ({
          credentials: [
            ...state.credentials.filter((c) => c.source !== cred.source),
            cred,
          ],
        }));
      },

      removeCredentials: (source) => {
        set((state) => ({
          credentials: state.credentials.filter((c) => c.source !== source),
        }));
      },

      // ===== UI ACTIONS (with mutual exclusion for panels) =====
      setLoading: (loading) => set({ isLoading: loading }),
      setFilterOpen: (open) => set(open ? {
        isFilterOpen: true, isSortOpen: false, isBatchPanelOpen: false, isLLMPanelOpen: false, isDetailOpen: null,
      } : { isFilterOpen: false }),
      setSortOpen: (open) => set(open ? {
        isSortOpen: true, isFilterOpen: false, isBatchPanelOpen: false, isLLMPanelOpen: false, isDetailOpen: null,
      } : { isSortOpen: false }),
      setBatchPanelOpen: (open) => set(open ? {
        isBatchPanelOpen: true, isFilterOpen: false, isSortOpen: false, isLLMPanelOpen: false, isDetailOpen: null,
      } : { isBatchPanelOpen: false }),
      setLLMPanelOpen: (open) => set(open ? {
        isLLMPanelOpen: true, isFilterOpen: false, isSortOpen: false, isBatchPanelOpen: false, isDetailOpen: null,
      } : { isLLMPanelOpen: false }),
      setDetailOpen: (id) => set(id ? {
        isDetailOpen: id, isFilterOpen: false, isSortOpen: false, isBatchPanelOpen: false, isLLMPanelOpen: false,
      } : { isDetailOpen: null }),
      setPage: (page) => set({ page }),
      setHasMore: (hasMore) => set({ hasMore }),
      setTotalCount: (count) => set({ totalCount: count }),
      setAnalytics: (data) => set({ analytics: data }),
    }),
    {
      name: 'internhub-store',
      partialize: (state) => ({
        appliedIds: Array.from(state.appliedIds),
        dismissedIds: Array.from(state.dismissedIds),
        viewedIds: Array.from(state.viewedIds),
        credentials: state.credentials,
        preferences: state.preferences,
        filters: state.filters,
        sort: state.sort,
      }),
      merge: (persisted: any, current) => ({
        ...current,
        ...persisted,
        appliedIds: new Set(persisted?.appliedIds || []),
        dismissedIds: new Set(persisted?.dismissedIds || []),
        viewedIds: new Set(persisted?.viewedIds || []),
        selectedIds: new Set(),
      }),
    }
  )
);
