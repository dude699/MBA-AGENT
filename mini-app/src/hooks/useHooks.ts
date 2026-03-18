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
import { ITEMS_PER_PAGE } from '@/utils/constants';
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
      toast.error('Select internships from a single source');
      return;
    }

    // Check if this source requires credentials
    const credReq = (await import('@/utils/constants')).CREDENTIAL_REQUIREMENTS;
    const needsCreds = credReq.some((c: any) => c.source === lockedSource);
    
    if (needsCreds) {
      // Check credentials for sources that need them
      const cred = credentials.find((c) => c.source === lockedSource);
      if (!cred || !cred.isValid) {
        toast.error(`Please add ${lockedSource} credentials first`);
        return;
      }
    }

    const { internships: storeInternships } = useAppStore.getState();
    const ids = Array.from(selectedIds);

    // For direct-apply sources (no credential requirements),
    // open each job URL in a new tab AND mark as applied via API
    if (!needsCreds) {
      startBatch();
      hapticFeedback('medium');
      let openedCount = 0;
      
      for (let i = 0; i < ids.length; i++) {
        if (useAppStore.getState().batch.status === 'paused') break;
        setBatchState({ currentIndex: i, status: 'running' });
        
        const item = storeInternships.find((int) => int.id === ids[i]);
        if (item?.sourceUrl) {
          window.open(item.sourceUrl, '_blank');
          openedCount++;
        }
        
        // Mark applied in backend
        try {
          await applyToInternship(ids[i], {});
        } catch {}
        
        markApplied(ids[i], 'applied');
        setBatchState({
          processedIds: [...useAppStore.getState().batch.processedIds, ids[i]],
          successCount: openedCount,
        });
        
        // Small delay between opens to avoid popup blockers
        if (i < ids.length - 1) {
          await new Promise((r) => setTimeout(r, 800));
        }
      }
      
      completeBatch();
      hapticFeedback('heavy');
      toast.success(`Opened ${openedCount} application pages`);
      return;
    }

    // For credential-based sources, use batch-apply API
    const cred = credentials.find((c) => c.source === lockedSource)!;
    startBatch();
    hapticFeedback('medium');

    try {
      // Call the batch-apply API endpoint
      const batchResult = await batchApplyToInternships(
        ids,
        cred.credentials,
        lockedSource
      );

      if (batchResult.success && batchResult.data) {
        const { results, summary } = batchResult.data;
        let successCount = 0;
        let failCount = 0;
        const processedIds: string[] = [];
        const failedIds: string[] = [];
        const errors: Array<{ internshipId: string; error: string; timestamp: string; retryable: boolean }> = [];

        for (const result of results) {
          const id = String(result.id);
          setBatchState({ currentIndex: processedIds.length + failedIds.length, status: 'running' });

          if (result.success) {
            markApplied(id, 'applied');
            successCount++;
            processedIds.push(id);

            // For auto_apply_failed, still open the URL as fallback
            if (result.method === 'auto_apply_failed' && result.source_url) {
              window.open(result.source_url, '_blank');
            }
          } else {
            failCount++;
            failedIds.push(id);
            errors.push({
              internshipId: id,
              error: result.error || 'Application failed',
              timestamp: new Date().toISOString(),
              retryable: true,
            });

            // Open the source URL as fallback for failed auto-apply
            if (result.source_url) {
              window.open(result.source_url, '_blank');
              markApplied(id, 'applied'); // Still mark since we opened the page
            }
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
        
        if (successCount > 0 && failCount === 0) {
          toast.success(`${successCount} applications submitted successfully!`);
        } else if (successCount > 0 && failCount > 0) {
          toast.success(`${successCount} applied, ${failCount} opened for manual apply`);
        } else {
          toast.error(`Auto-apply failed. ${failCount} pages opened for manual application.`);
        }
      } else {
        // API call failed entirely — fallback to opening URLs
        let openedCount = 0;
        for (const id of ids) {
          const item = storeInternships.find((int) => int.id === id);
          if (item?.sourceUrl) {
            window.open(item.sourceUrl, '_blank');
            markApplied(id, 'applied');
            openedCount++;
          }
        }
        completeBatch();
        hapticFeedback('medium');
        toast.error(`Server error. Opened ${openedCount} pages for manual apply.`);
      }
    } catch (err: any) {
      // Network error — fallback to opening URLs
      let openedCount = 0;
      for (const id of ids) {
        const item = storeInternships.find((int) => int.id === id);
        if (item?.sourceUrl) {
          window.open(item.sourceUrl, '_blank');
          markApplied(id, 'applied');
          openedCount++;
        }
      }
      completeBatch();
      hapticFeedback('medium');
      toast.error(`Connection error. Opened ${openedCount} pages for manual apply.`);
    }
  }, [selectedIds, lockedSource, credentials, batch]);

  return {
    executeBatch,
    isRunning: batch.status === 'running',
    progress: batch.totalCount > 0 ? (batch.currentIndex / batch.totalCount) * 100 : 0,
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
