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
// v4.0: COMPLETE REWRITE — fixes "Application processed" false positive.
// ROOT CAUSE: backend returns success:true + method:'direct' for ALL sources
// meaning "we recorded it" not "we applied". Frontend was treating ALL
// success:true as "applied" which is WRONG.
// 
// FIX 1: Only count method:'auto_applied' as real success. Everything else
//        is manual-apply-needed.
// FIX 2: window.open() is BLOCKED by popup blockers on Telegram Desktop
//        and most browsers. Instead, we store URLs in batch state and
//        render clickable links in the BatchApplyPanel completion UI.
// FIX 3: Show real-time step-by-step toast notifications during apply.
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
      } else if (selectedSources.size > 1) {
        toast.error('Selected internships are from multiple sources. Please select from only one source.');
        return;
      } else {
        toast.error('Could not determine source. Please deselect and reselect internships.');
        return;
      }
    }

    const currentLockedSource = useAppStore.getState().lockedSource;
    const normalizedLockedSource = (currentLockedSource || lockedSource || '').toLowerCase().trim();

    if (!normalizedLockedSource) {
      toast.error('Could not determine source. Please try again.');
      return;
    }

    const needsCreds = CREDENTIAL_REQUIREMENTS.some((c: any) => (c.source || '').toLowerCase() === normalizedLockedSource);
    const cred = credentials.find((c) => (c.source || '').toLowerCase() === normalizedLockedSource);

    if (needsCreds && (!cred || !cred.isValid)) {
      toast.error(`Please add ${lockedSource} credentials first`);
      return;
    }

    const ids = Array.from(selectedIds);

    startBatch();
    hapticFeedback('medium');

    // Step 1: Notify user the process is starting
    toast.loading('Connecting to server...', { id: 'batch-step' });

    try {
      let batchResult: any;
      try {
        // Step 2: Sending to backend
        toast.loading(`Sending ${ids.length} applications to server...`, { id: 'batch-step' });
        batchResult = await batchApplyToInternships(
          ids,
          cred?.credentials || {},
          normalizedLockedSource
        );
        toast.dismiss('batch-step');
      } catch (apiErr: any) {
        toast.dismiss('batch-step');
        completeBatch();
        hapticFeedback('medium');
        toast.error('Connection error. Check your internet and try again.');
        return;
      }

      if (batchResult.success && batchResult.data) {
        const results = batchResult.data?.results || [];
        let autoAppliedCount = 0;
        let manualNeededCount = 0;
        let failCount = 0;
        const processedIds: string[] = [];
        const failedIds: string[] = [];
        const errors: Array<{ internshipId: string; error: string; timestamp: string; retryable: boolean }> = [];
        // CRITICAL: Store URLs for manual apply — rendered as clickable links, NOT window.open()
        const manualApplyLinks: Array<{ id: string; url: string; title: string; company: string }> = [];

        // Resolve job details for nice names
        const sbCache = ((window as any).__sbJobsCache || []) as any[];
        const storeJobs = useAppStore.getState().internships;
        const allJobs = [...storeJobs, ...sbCache];

        // PRISM v4.0: Track assisted-apply links with cover letters
        const assistedApplyLinks: Array<{ id: string; url: string; title: string; company: string; coverLetter: string }> = [];

        for (let i = 0; i < results.length; i++) {
          const result = results[i];
          const id = String(result?.id || ids[i] || '');
          const job = allJobs.find((j: any) => String(j.id) === id);
          const jobTitle = job?.title || `Job #${id}`;
          const jobCompany = job?.company || '';

          setBatchState({ currentIndex: i, status: 'running' });

          // Step-by-step toast: show what's happening for each job
          toast.loading(`Processing ${i + 1}/${results.length}: ${jobTitle.slice(0, 40)}...`, { id: 'batch-step' });

          // Show backend step logs as individual toasts (real-time feedback)
          const steps: string[] = result?.steps || [];
          for (const step of steps) {
            toast.loading(`${i + 1}/${results.length}: ${step}`, { id: 'batch-step' });
            await new Promise((r) => setTimeout(r, 400));
          }

          try {
            if (result?.success && result?.method === 'auto_applied') {
              // ===== REAL AUTO-APPLY: Backend A-13 submitted the application =====
              markApplied(id, 'applied');
              autoAppliedCount++;
              processedIds.push(id);
              toast.success(`\u2705 Auto-applied: ${jobTitle.slice(0, 35)}`, { duration: 3000 });
            } else if (result?.success && result?.method === 'assisted') {
              // ===== ASSISTED-APPLY (v4.0): Cover letter generated, user clicks link =====
              processedIds.push(id);
              manualNeededCount++;
              const sourceUrl = result?.source_url || job?.sourceUrl || '';
              const coverLetter = result?.cover_letter || '';
              if (sourceUrl) {
                assistedApplyLinks.push({ id, url: sourceUrl, title: jobTitle, company: jobCompany, coverLetter });
                manualApplyLinks.push({ id, url: sourceUrl, title: jobTitle, company: jobCompany });
              }
              toast(`\u270D Cover letter ready for ${jobTitle.slice(0, 30)} \u2014 NOT yet applied, click link below`, { icon: '\u270D\uFE0F', duration: 4000 });
            } else if (result?.success) {
              // ===== NOT AUTO-APPLIED: Backend only RECORDED it =====
              // method is 'direct' or 'auto_apply_failed' or 'auto_apply_error'
              // This means the user MUST manually apply
              processedIds.push(id);
              manualNeededCount++;
              const sourceUrl = result?.source_url || job?.sourceUrl || '';
              if (sourceUrl) {
                manualApplyLinks.push({ id, url: sourceUrl, title: jobTitle, company: jobCompany });
              }
              // Show honest toast about what happened
              if (result?.method === 'auto_apply_failed') {
                const reason = result?.error ? `: ${(result.error as string).slice(0, 60)}` : '';
                toast(`\u26A0\uFE0F ${jobTitle.slice(0, 30)} \u2014 auto-apply failed${reason}`, { duration: 3500 });
              } else {
                toast(`\uD83D\uDC49 ${jobTitle.slice(0, 30)} \u2014 click link below to apply`, { duration: 2500 });
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
              toast.error(`\u274C Failed: ${jobTitle.slice(0, 35)} \u2014 ${(result?.error || '').slice(0, 50)}`, { duration: 3000 });
            }
          } catch (itemErr) {
            failCount++;
            failedIds.push(id);
          }

          if (i < results.length - 1) {
            await new Promise((r) => setTimeout(r, 300));
          }
        }

        toast.dismiss('batch-step');

        // Store manual apply links in batch state so the UI can render clickable links
        setBatchState({
          processedIds,
          failedIds,
          successCount: autoAppliedCount,
          failCount,
          errors,
          manualApplyLinks: manualApplyLinks as any,
          assistedApplyLinks: assistedApplyLinks as any,
          manualNeededCount,
        });

        completeBatch();
        hapticFeedback('heavy');

        // ===== HONEST TOAST MESSAGES =====
        if (autoAppliedCount > 0 && manualNeededCount === 0 && failCount === 0) {
          toast.success(`${autoAppliedCount} application${autoAppliedCount > 1 ? 's' : ''} submitted automatically!`, { duration: 4000 });
        } else if (autoAppliedCount > 0 && manualNeededCount > 0) {
          toast.success(`${autoAppliedCount} auto-submitted! ${manualNeededCount} need manual apply \u2014 see links below.`, { duration: 5000 });
        } else if (manualNeededCount > 0 && failCount === 0) {
          // Cover letters generated, user clicks links to apply
          if (assistedApplyLinks.length > 0) {
            toast(`Cover letters ready for ${manualNeededCount} listing${manualNeededCount > 1 ? 's' : ''}. NOT applied yet \u2014 click links below to apply manually.`, { icon: '\u270D\uFE0F', duration: 6000 });
          } else {
            toast(`${manualNeededCount} listing${manualNeededCount > 1 ? 's' : ''} need manual apply. Click the links below to open them.`, { icon: '\uD83D\uDC47', duration: 6000 });
          }
        } else if (failCount > 0 && (autoAppliedCount + manualNeededCount) > 0) {
          toast(`${autoAppliedCount} auto-applied, ${manualNeededCount} need manual, ${failCount} failed.`, { icon: '\u2139\uFE0F', duration: 5000 });
        } else if (failCount > 0) {
          toast.error(`All ${failCount} applications failed. Please try again.`);
        } else if (results.length === 0) {
          toast.error('No results from server. Please try again.');
        }
      } else {
        completeBatch();
        hapticFeedback('medium');
        const errorMsg = batchResult?.error || 'Server error';
        toast.error(`${errorMsg}. Please try again.`);
      }
    } catch (err: any) {
      try { toast.dismiss('batch-step'); } catch {}
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
