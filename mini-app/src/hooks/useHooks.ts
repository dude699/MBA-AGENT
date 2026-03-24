// ============================================================
// INTERNSHIP HUB — CUSTOM REACT HOOKS
// ============================================================

import { useEffect, useState, useCallback, useRef, useMemo } from 'react';
import { useQuery, useInfiniteQuery } from '@tanstack/react-query';
import { useAppStore } from '@/store/useAppStore';
import {
  fetchInternships,
  fetchInternshipById,
  fetchAnalytics,
  applyToInternship,
  batchApplyToInternships,
  chatWithLLM,
} from '@/services/api';
import { applyFilters, applySorting, deduplicateInternships, hapticFeedback } from '@/utils/helpers';
import { ITEMS_PER_PAGE, CREDENTIAL_REQUIREMENTS } from '@/utils/constants';
import type { Internship, FilterState, SortField, InternshipSource } from '@/types';
import toast from 'react-hot-toast';

// ===== INTERNSHIP LIST WITH PAGINATION =====
export function useInternships() {
  const { filters, sort, setInternships, appendInternships, setLoading, setHasMore, setTotalCount, page, setPage, dismissedIds } = useAppStore();

  const query = useInfiniteQuery({
    queryKey: ['internships', filters, sort],
    queryFn: async ({ pageParam = 1 }) => {
      return fetchInternships(pageParam, ITEMS_PER_PAGE, filters, sort);
    },
    initialPageParam: 1,
    getNextPageParam: (lastPage) => {
      if (lastPage.meta?.hasMore) {
        return (lastPage.meta?.page || 1) + 1;
      }
      return undefined;
    },
  });

  useEffect(() => {
    if (query.data?.pages) {
      const allItems = query.data.pages.flatMap((p) => p.data);
      // Filter out dismissed and expired
      const filtered = allItems.filter(
        (item) => !dismissedIds.has(item.id) && !item.isExpired
      );
      const deduped = deduplicateInternships(filtered);
      setInternships(deduped);
      const lastPage = query.data.pages[query.data.pages.length - 1];
      setHasMore(lastPage.meta?.hasMore || false);
      setTotalCount(lastPage.meta?.total || 0);
    }
  }, [query.data]);

  useEffect(() => {
    setLoading(query.isLoading || query.isFetchingNextPage);
  }, [query.isLoading, query.isFetchingNextPage]);

  return {
    ...query,
    loadMore: () => {
      if (query.hasNextPage && !query.isFetchingNextPage) {
        query.fetchNextPage();
      }
    },
  };
}

// ===== FILTERED & SORTED INTERNSHIPS =====
export function useFilteredInternships() {
  const { internships, filters, sort } = useAppStore();

  return useMemo(() => {
    let result = applyFilters(internships, filters);
    result = applySorting(result, sort);
    return deduplicateInternships(result);
  }, [internships, filters, sort]);
}

// ===== SINGLE INTERNSHIP DETAIL =====
export function useInternshipDetail(id: string | null) {
  return useQuery({
    queryKey: ['internship', id],
    queryFn: () => fetchInternshipById(id!),
    enabled: !!id,
  });
}

// ===== ANALYTICS =====
export function useAnalytics() {
  return useQuery({
    queryKey: ['analytics'],
    queryFn: fetchAnalytics,
    staleTime: 60_000,
  });
}

// ===== BATCH APPLY =====
// v3.0: ALL sources go through backend batch-apply API for real application.
// The backend handles auto-apply via A-13 for supported sources (internshala,
// naukri, greenhouse, lever) and marks as applied for tracking.
// NO MORE window.open() as primary action — that was the entire bug.
export function useBatchApply() {
  const {
    batch, selectedIds, lockedSource, credentials,
    setBatchState, startBatch, completeBatch, cancelBatch, markApplied,
  } = useAppStore();

  const executeBatch = useCallback(async () => {
    if (selectedIds.size === 0) {
      toast.error('No internships selected');
      return;
    }

    if (!lockedSource) {
      // Try to auto-detect source from selected internships
      const sbCache = ((window as any).__sbJobsCache || []) as any[];
      const storeJobs = useAppStore.getState().internships;
      const allJobs = [...storeJobs, ...sbCache];
      const selectedSources = new Set<string>();
      for (const id of selectedIds) {
        const job = allJobs.find((j: any) => j.id === id);
        if (job) selectedSources.add((job.source || '').toLowerCase().trim());
      }
      if (selectedSources.size === 1) {
        const detectedSource = [...selectedSources][0];
        useAppStore.getState().setLockedSource(detectedSource as any);
        // Continue with detected source
      } else if (selectedSources.size > 1) {
        toast.error('Selected internships are from multiple sources. Please select from only one source.');
        return;
      } else {
        toast.error('Could not determine source. Please deselect and reselect internships.');
        return;
      }
    }

    // Re-read lockedSource in case it was auto-detected above
    const currentLockedSource = useAppStore.getState().lockedSource;
    const normalizedLockedSource = (currentLockedSource || lockedSource || '').toLowerCase().trim();

    if (!normalizedLockedSource) {
      toast.error('Could not determine source. Please try again.');
      return;
    }

    // Check if this source has credential requirements
    const needsCreds = CREDENTIAL_REQUIREMENTS.some((c: any) => (c.source || '').toLowerCase() === normalizedLockedSource);

    // Get credentials if they exist (optional for some sources) — case-insensitive
    const cred = credentials.find((c) => (c.source || '').toLowerCase() === normalizedLockedSource);

    if (needsCreds && (!cred || !cred.isValid)) {
      toast.error(`Please add ${lockedSource} credentials first`);
      return;
    }

    const ids = Array.from(selectedIds);

    startBatch();
    hapticFeedback('medium');

    try {
      // ALL sources now go through the batch-apply API.
      // The backend will:
      //   1. For credential sources (internshala, naukri, greenhouse, lever):
      //      attempt real auto-apply via A-13
      //   2. For all sources: record the application in the database
      //   3. Return results with source_url ONLY as fallback info
      // Wrap the entire batch API call in a robust try-catch
      let batchResult: any;
      try {
        batchResult = await batchApplyToInternships(
          ids,
          cred?.credentials || {},
          normalizedLockedSource
        );
      } catch (apiErr: any) {
        // Network/fetch-level error — complete batch gracefully
        completeBatch();
        hapticFeedback('medium');
        toast.error('Connection error. Please check your internet and try again.');
        return;
      }

      if (batchResult.success && batchResult.data) {
        const results = batchResult.data?.results || [];
        let successCount = 0;
        let failCount = 0;
        const processedIds: string[] = [];
        const failedIds: string[] = [];
        const errors: Array<{ internshipId: string; error: string; timestamp: string; retryable: boolean }> = [];
        // Track URLs that need manual apply
        const manualApplyUrls: string[] = [];

        for (let i = 0; i < results.length; i++) {
          const result = results[i];
          const id = String(result?.id || ids[i] || '');
          setBatchState({ currentIndex: i, status: 'running' });

          try {
            if (result?.success && result?.method === 'auto_applied') {
              // Truly auto-applied by backend A-13
              markApplied(id, 'applied');
              successCount++;
              processedIds.push(id);
            } else if (result?.success) {
              // Backend recorded it but auto-apply failed or not supported
              // CRITICAL FIX: collect source URLs for manual apply
              processedIds.push(id);
              successCount++;
              const sourceUrl = result?.source_url || '';
              if (sourceUrl && (result?.method === 'auto_apply_failed' || result?.method === 'auto_apply_error' || result?.method === 'direct')) {
                manualApplyUrls.push(sourceUrl);
              }
            } else {
              failCount++;
              failedIds.push(id);
              errors.push({
                internshipId: id,
                error: result?.error || 'Application failed',
                timestamp: new Date().toISOString(),
                retryable: true,
              });
            }
          } catch (itemErr) {
            failCount++;
            failedIds.push(id);
          }

          if (i < results.length - 1) {
            await new Promise((r) => setTimeout(r, 150));
          }
        }

        setBatchState({
          processedIds,
          failedIds,
          successCount,
          failCount,
          errors,
        });

        completeBatch();
        hapticFeedback('heavy');

        // CRITICAL FIX: Open source URLs for jobs that need manual apply
        // This is what was missing — users were told to "apply manually"
        // but had NO way to actually reach the listing URL!
        if (manualApplyUrls.length > 0) {
          // Open first URL immediately, queue rest with small delays
          for (let i = 0; i < Math.min(manualApplyUrls.length, 5); i++) {
            const url = manualApplyUrls[i];
            if (url) {
              if (i === 0) {
                window.open(url, '_blank');
              } else {
                setTimeout(() => window.open(url, '_blank'), i * 800);
              }
            }
          }
        }

        // Show clear toast based on results
        const autoApplied = results.filter((r: any) => r?.method === 'auto_applied').length;
        const manualCount = manualApplyUrls.length;

        if (autoApplied > 0 && manualCount === 0 && failCount === 0) {
          toast.success(`${autoApplied} application${autoApplied > 1 ? 's' : ''} submitted automatically!`);
        } else if (autoApplied > 0 && manualCount > 0) {
          toast.success(`${autoApplied} auto-submitted! ${manualCount} opened for manual apply.`);
        } else if (manualCount > 0 && failCount === 0) {
          toast(`${manualCount} listing${manualCount > 1 ? 's' : ''} opened in browser. Complete your application there.`, { icon: '\uD83D\uDD17', duration: 5000 });
        } else if (successCount > 0 && failCount > 0) {
          toast.success(`${successCount} processed, ${failCount} failed.`);
        } else if (failCount > 0) {
          toast.error(`${failCount} application${failCount > 1 ? 's' : ''} failed. Try again or apply manually.`);
        } else if (results.length === 0) {
          toast.error('No results returned from server. Please try again.');
        } else {
          toast('Applications processed.', { icon: '\u2139\uFE0F' });
        }
      } else {
        // API returned error or empty result
        completeBatch();
        hapticFeedback('medium');
        const errorMsg = batchResult?.error || 'Server error';
        toast.error(`${errorMsg}. Please try again.`);
      }
    } catch (err: any) {
      // Unexpected error in the entire flow
      try { completeBatch(); } catch {}
      hapticFeedback('medium');
      toast.error('Unexpected error. Please try again.');
    }
  }, [selectedIds, lockedSource, credentials, batch]);

  return {
    executeBatch,
    isRunning: batch.status === 'running',
    progress: batch.totalCount > 0 ? ((batch.currentIndex + 1) / batch.totalCount) * 100 : 0,
  };
}

// ===== LLM CHAT (v4.0 - CV-aware from localStorage, profile-aware, anti-hallucination) =====
export function useLLMChat() {
  const { addLLMMessage, setLLMLoading, llmLoading, llmMessages, internships } = useAppStore();

  const sendMessage = useCallback(async (message: string, profile: string = 'generalist', internshipIds?: string[]) => {
    addLLMMessage({ role: 'user', content: message });
    setLLMLoading(true);

    // Build condensed history (last 3 exchanges = 6 msgs)
    const history = llmMessages.slice(-6).map((msg) => ({
      role: msg.role,
      content: msg.content.slice(0, 500),
    }));

    // Get Telegram user ID for personalized context (CV + profile)
    let telegramId = '';
    try {
      const tgUser = window.Telegram?.WebApp?.initDataUnsafe?.user;
      if (tgUser?.id) telegramId = String(tgUser.id);
    } catch {}

    // Read CV info from localStorage for client-side context
    let cvText = '';
    try {
      const cvName = localStorage.getItem('internhub_cv_name');
      const cvUploadedAt = localStorage.getItem('internhub_cv_uploaded_at');
      if (cvName) {
        cvText = `[User has uploaded CV: ${cvName}, uploaded on ${cvUploadedAt || 'unknown date'}]`;
      }
    } catch {}

    // Read user profile from localStorage
    let userProfile: Record<string, string> = {};
    try {
      const stored = localStorage.getItem('internhub_user_profile');
      if (stored) {
        userProfile = JSON.parse(stored);
      }
    } catch {}

    // Resource context: tell backend how many jobs are loaded client-side
    const resourceContext = {
      internshipIds,
      clientJobCount: internships.length,
      hasLoadedJobs: internships.length > 0,
      telegramId,
      cvText,
      userProfile,
    };

    try {
      const response = await chatWithLLM(message, profile, history, resourceContext);
      if (response.success && response.data) {
        addLLMMessage({
          role: 'assistant',
          content: response.data,
          metadata: {
            model: (response as any).meta?.model || 'groq-llama3',
            provider: (response as any).meta?.provider,
            profile: profile,
            internshipIds,
          },
        });
      } else {
        addLLMMessage({
          role: 'assistant',
          content: response.data || 'I could not generate a response. Please check your connection and try again.',
          metadata: { profile },
        });
      }
    } catch (err: any) {
      addLLMMessage({
        role: 'assistant',
        content: 'I\'m having trouble connecting to the AI service. Please check your internet connection and try again in a moment.',
        metadata: { profile },
      });
    } finally {
      setLLMLoading(false);
    }
  }, [llmMessages, internships.length]);

  return { sendMessage, isLoading: llmLoading };
}

// ===== INFINITE SCROLL =====
export function useInfiniteScroll(callback: () => void, hasMore: boolean) {
  const observer = useRef<IntersectionObserver | null>(null);
  const sentinelRef = useCallback(
    (node: HTMLElement | null) => {
      if (observer.current) observer.current.disconnect();
      if (!hasMore) return;

      observer.current = new IntersectionObserver(
        (entries) => {
          if (entries[0].isIntersecting) {
            callback();
          }
        },
        { rootMargin: '200px' }
      );

      if (node) observer.current.observe(node);
    },
    [callback, hasMore]
  );

  return sentinelRef;
}

// ===== DEBOUNCE =====
export function useDebounce<T>(value: T, delay: number): T {
  const [debouncedValue, setDebouncedValue] = useState(value);

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedValue(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);

  return debouncedValue;
}

// ===== COUNTDOWN TIMER =====
export function useCountdown(targetDate: string | null | undefined) {
  const [remaining, setRemaining] = useState('');
  const [isComplete, setIsComplete] = useState(false);

  useEffect(() => {
    if (!targetDate) {
      setIsComplete(true);
      return;
    }

    const interval = setInterval(() => {
      const now = Date.now();
      const target = new Date(targetDate).getTime();
      const diff = target - now;

      if (diff <= 0) {
        setIsComplete(true);
        setRemaining('Ready');
        clearInterval(interval);
        return;
      }

      const mins = Math.floor(diff / 60000);
      const secs = Math.floor((diff % 60000) / 1000);
      setRemaining(`${mins}m ${secs}s`);
      setIsComplete(false);
    }, 1000);

    return () => clearInterval(interval);
  }, [targetDate]);

  return { remaining, isComplete };
}
