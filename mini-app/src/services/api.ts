// ============================================================
// INTERNSHIP HUB — API SERVICE (REAL BACKEND CONNECTION)
// ============================================================
// Connects to the Operation First Mover Python backend API.
// Falls back to offline mock data if backend is unreachable.
// ============================================================

import type {
  Internship, FilterState, SortField, PaginatedResponse,
  AnalyticsData, InternshipSource, APIResponse, ApplicationStatus,
} from '@/types';
import { API_BASE_URL, ITEMS_PER_PAGE } from '@/utils/constants';
import { generateHash } from '@/utils/helpers';

// ===== SESSION TOKEN MANAGEMENT =====
let sessionToken: string | null = null;

export function setSessionToken(token: string) {
  sessionToken = token;
  try {
    localStorage.setItem('internhub_session', token);
  } catch {}
}

export function getSessionToken(): string | null {
  if (sessionToken) return sessionToken;
  try {
    sessionToken = localStorage.getItem('internhub_session');
  } catch {}
  return sessionToken;
}

function getHeaders(): Record<string, string> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };
  const token = getSessionToken();
  if (token) {
    headers['X-Session-Token'] = token;
  }
  return headers;
}

// ===== SORT FIELD MAPPING (frontend -> backend) =====
// Backend sort_map supports: 'stipend', 'ppo', 'date', 'duration', 'applicants'
// CRITICAL: Client-side sorting is AUTHORITATIVE (useFilteredInternships does the real sort).
// Backend sort only matters for initial data ordering — client re-sorts locally.
function mapSortField(sort: SortField): string {
  const map: Record<string, string> = {
    stipend_high: 'stipend',
    stipend_low: 'stipend',
    duration_short: 'duration',
    duration_long: 'duration',
    match_score: 'ppo',
    success_rate: 'ppo',
    posted_recent: 'date',
    posted_oldest: 'date',
    deadline_soon: 'date',
    deadline_later: 'date',
    applicants_low: 'applicants',
    applicants_high: 'applicants',
    ghost_score_low: 'ppo',
    company_rating: 'ppo',
    openings_high: 'ppo',
    response_time: 'date',
  };
  return map[sort] || 'stipend';
}

// ===== DETERMINE BACKEND URL =====
function getApiUrl(path: string): string {
  // In production (Telegram Mini App), API is on the same origin
  // In development, Vite proxy handles /api -> localhost:4000
  return `${API_BASE_URL}${path}`;
}

// ===== MAIN API FUNCTIONS =====

export async function fetchInternships(
  page: number = 1,
  pageSize: number = ITEMS_PER_PAGE,
  filters: FilterState = {} as FilterState,
  sort: SortField = 'stipend_high'
): Promise<PaginatedResponse<Internship>> {
  try {
    const params = new URLSearchParams();
    params.set('page', String(page));
    params.set('per_page', String(pageSize));
    params.set('sort', mapSortField(sort));

    // Map ALL filters to backend query params
    if (filters.categories?.length > 0) {
      params.set('category', filters.categories.map(c => c.toLowerCase()).join(','));
    }
    if (filters.sources?.length > 0) {
      params.set('source', filters.sources.map(s => s.toLowerCase()).join(','));
    }
    if (filters.locations?.length > 0) {
      params.set('location', filters.locations.map(l => l.toLowerCase()).join(','));
    }
    if (filters.stipendMin && filters.stipendMin > 0) {
      params.set('min_stipend', String(filters.stipendMin));
    }
    if (filters.durationMax && filters.durationMax < 12) {
      params.set('max_duration', String(filters.durationMax));
    } else {
      params.set('max_duration', '12');
    }
    if (filters.search) {
      params.set('search', filters.search);
    }
    if (filters.onlyWithStipend) {
      params.set('min_stipend', String(Math.max(filters.stipendMin || 0, 1)));
    }

    const resp = await fetch(`${getApiUrl('/internships')}?${params.toString()}`, {
      headers: getHeaders(),
    });

    if (!resp.ok) {
      throw new Error(`API error: ${resp.status}`);
    }

    const data = await resp.json();
    if (!data.success) {
      throw new Error(data.error || 'API returned error');
    }

    // Ensure each item has required fields
    const items: Internship[] = (data.data || []).map((item: any) => ensureInternshipFields(item));

    return {
      success: true,
      data: items,
      meta: {
        total: data.meta?.total || items.length,
        page: data.meta?.page || page,
        pageSize: data.meta?.pageSize || pageSize,
        hasMore: data.meta?.hasMore || false,
        filters,
        sort,
      },
      timestamp: data.timestamp || new Date().toISOString(),
    };
  } catch (error) {
    console.warn('[API] fetchInternships failed, using fallback:', error);
    return fallbackFetchInternships(page, pageSize, filters, sort);
  }
}

export async function fetchInternshipById(id: string): Promise<APIResponse<Internship | null>> {
  try {
    const resp = await fetch(getApiUrl(`/internships/${id}`), {
      headers: getHeaders(),
    });

    if (!resp.ok) {
      throw new Error(`API error: ${resp.status}`);
    }

    const data = await resp.json();
    if (!data.success) {
      return { success: false, data: null, timestamp: new Date().toISOString() };
    }

    return {
      success: true,
      data: ensureInternshipFields(data.data),
      timestamp: data.timestamp || new Date().toISOString(),
    };
  } catch (error) {
    console.warn('[API] fetchInternshipById failed:', error);
    return { success: false, data: null, timestamp: new Date().toISOString() };
  }
}

export async function fetchAnalytics(): Promise<APIResponse<AnalyticsData>> {
  try {
    const resp = await fetch(getApiUrl('/analytics'), {
      headers: getHeaders(),
    });

    if (!resp.ok) {
      throw new Error(`API error: ${resp.status}`);
    }

    const data = await resp.json();
    if (!data.success) {
      throw new Error(data.error || 'Analytics API error');
    }

    return {
      success: true,
      data: data.data,
      timestamp: data.timestamp || new Date().toISOString(),
    };
  } catch (error) {
    console.warn('[API] fetchAnalytics failed, using fallback:', error);
    return fallbackFetchAnalytics();
  }
}

export async function applyToInternship(id: string, _credentials: Record<string, string>): Promise<APIResponse<{ status: ApplicationStatus; apply_result?: any }>> {
  try {
    const resp = await fetch(getApiUrl(`/apply/${id}`), {
      method: 'POST',
      headers: getHeaders(),
      body: JSON.stringify({ credentials: _credentials }),
    });

    if (!resp.ok) {
      throw new Error(`API error: ${resp.status}`);
    }

    const data = await resp.json();
    return {
      success: data.success,
      data: {
        status: data.success ? 'applied' : 'not_applied',
        apply_result: data.data?.apply_result,
      },
      error: data.error,
      timestamp: data.timestamp || new Date().toISOString(),
    };
  } catch (error) {
    console.warn('[API] applyToInternship failed:', error);
    return {
      success: false,
      data: { status: 'not_applied' },
      error: 'Failed to connect to server. Try using /apply in the Telegram bot.',
      timestamp: new Date().toISOString(),
    };
  }
}

export async function batchApplyToInternships(
  listingIds: string[],
  credentials: Record<string, string>,
  source: string
): Promise<APIResponse<{
  results: Array<{ id: number; success: boolean; method: string; source_url: string; error: string }>;
  summary: { total: number; success: number; failed: number };
}>> {
  try {
    const resp = await fetch(getApiUrl('/batch-apply'), {
      method: 'POST',
      headers: getHeaders(),
      body: JSON.stringify({
        listing_ids: listingIds.map(id => {
          // Keep sb_ prefixed IDs as strings, parse others to int
          if (typeof id === 'string' && id.startsWith('sb_')) return id;
          const parsed = parseInt(id, 10);
          return isNaN(parsed) ? id : parsed;
        }),
        credentials,
        source: (source || '').toLowerCase(),
      }),
    });

    if (!resp.ok) {
      throw new Error(`API error: ${resp.status}`);
    }

    const data = await resp.json();
    return {
      success: data.success,
      data: data.data,
      error: data.error,
      timestamp: data.timestamp || new Date().toISOString(),
    };
  } catch (error) {
    console.warn('[API] batchApplyToInternships failed:', error);
    return {
      success: false,
      data: { results: [], summary: { total: 0, success: 0, failed: 0 } },
      error: 'Failed to connect to batch-apply server.',
      timestamp: new Date().toISOString(),
    };
  }
}

export async function chatWithLLM(
  message: string,
  profile: string = 'generalist',
  history: Array<{ role: string; content: string }> = [],
  context?: { internshipIds?: string[]; clientJobCount?: number; hasLoadedJobs?: boolean; telegramId?: string; cvText?: string; userProfile?: Record<string, string> }
): Promise<APIResponse<string>> {
  try {
    // Build enriched context with CV data and user profile from localStorage
    let cvText = context?.cvText || '';
    let userProfile = context?.userProfile || {};
    let telegramId = context?.telegramId || '';

    // Read CV text from localStorage if not provided
    if (!cvText) {
      try {
        const storedCv = localStorage.getItem('internhub_cv_data');
        if (storedCv) {
          // Extract text content summary from base64 PDF (send the name at least)
          const cvName = localStorage.getItem('internhub_cv_name') || '';
          cvText = `[CV Uploaded: ${cvName}]`;
        }
      } catch {}
    }

    // Read user profile from localStorage if not provided
    if (!userProfile || Object.keys(userProfile).length === 0) {
      try {
        const storedProfile = localStorage.getItem('internhub_user_profile');
        if (storedProfile) {
          userProfile = JSON.parse(storedProfile);
        }
      } catch {}
    }

    const resp = await fetch(getApiUrl('/llm/chat'), {
      method: 'POST',
      headers: getHeaders(),
      body: JSON.stringify({
        message,
        profile,
        history: history.slice(-6), // Send last 3 exchanges for better context
        context: {
          internshipIds: context?.internshipIds,
          clientJobCount: context?.clientJobCount || 0,
          hasLoadedJobs: context?.hasLoadedJobs || false,
          telegramId,
          cvText,
          userProfile,
        },
      }),
    });

    if (!resp.ok) {
      throw new Error(`API error: ${resp.status}`);
    }

    const data = await resp.json();
    return {
      success: data.success,
      data: data.data || 'No response from AI.',
      meta: data.meta,
      timestamp: data.timestamp || new Date().toISOString(),
    };
  } catch (error) {
    console.warn('[API] chatWithLLM failed:', error);
    return {
      success: true,
      data: (
        "**I'm having trouble connecting to the AI backend.**\n\n" +
        "Try using these Telegram bot commands instead:\n" +
        "- `/package [id]` - Full application package\n" +
        "- `/cover [id]` - AI cover letter\n" +
        "- `/ats [id]` - ATS keyword analysis\n\n" +
        "The bot has direct access to the AI engine."
      ),
      timestamp: new Date().toISOString(),
    };
  }
}

export async function fetchSearchSuggestions(query: string): Promise<string[]> {
  // Client-side search suggestions from loaded data
  return [];
}

// ===== SESSION COOKIE VALIDATION =====
export async function validateSessionCookie(
  source: string,
  sessionCookie: string
): Promise<APIResponse<{ valid: boolean; message: string; username: string }>> {
  try {
    const resp = await fetch(getApiUrl('/validate-session'), {
      method: 'POST',
      headers: getHeaders(),
      body: JSON.stringify({ source, session_cookie: sessionCookie }),
    });

    if (!resp.ok) {
      throw new Error(`API error: ${resp.status}`);
    }

    const data = await resp.json();
    return {
      success: data.success,
      data: {
        valid: data.valid || false,
        message: data.message || '',
        username: data.username || '',
      },
      error: data.error,
      timestamp: new Date().toISOString(),
    };
  } catch (error) {
    console.warn('[API] validateSessionCookie failed:', error);
    return {
      success: false,
      data: { valid: false, message: 'Connection error', username: '' },
      error: 'Failed to validate session cookie',
      timestamp: new Date().toISOString(),
    };
  }
}

// ===== INTERNSHALA AUTO-LOGIN =====
export async function loginToInternshala(
  email: string,
  password: string,
  captchaApiKey: string = '',
  captchaProvider: string = 'capsolver',
): Promise<APIResponse<{ session_valid: boolean; message: string; username: string; needs_captcha_key?: boolean }>> {
  try {
    const resp = await fetch(getApiUrl('/internshala-login'), {
      method: 'POST',
      headers: getHeaders(),
      body: JSON.stringify({
        email,
        password,
        captcha_api_key: captchaApiKey,
        captcha_provider: captchaProvider,
      }),
    });

    if (!resp.ok) {
      throw new Error(`API error: ${resp.status}`);
    }

    const data = await resp.json();
    return {
      success: data.success,
      data: {
        session_valid: data.session_valid || false,
        message: data.message || data.error || '',
        username: data.username || '',
        needs_captcha_key: data.needs_captcha_key || false,
      },
      error: data.error,
      timestamp: new Date().toISOString(),
    };
  } catch (error) {
    console.warn('[API] loginToInternshala failed:', error);
    return {
      success: false,
      data: { session_valid: false, message: 'Connection error', username: '', needs_captcha_key: false },
      error: 'Failed to connect to server',
      timestamp: new Date().toISOString(),
    };
  }
}

// ===== SUPABASE PERSISTENT DATABASE API =====

export async function fetchSupabaseLatestJobs(
  page: number = 1,
  pageSize: number = ITEMS_PER_PAGE,
  filters: Partial<FilterState> = {},
  sort: string = 'date'
): Promise<PaginatedResponse<Internship>> {
  try {
    const params = new URLSearchParams();
    params.set('page', String(page));
    params.set('per_page', String(pageSize));
    params.set('sort', sort);

    if (filters.sources?.length) params.set('source', filters.sources.join(','));
    if (filters.categories?.length) params.set('category', filters.categories.join(','));
    if (filters.locations?.length) params.set('location', filters.locations.join(','));
    if (filters.search) params.set('search', filters.search);
    if (filters.onlyWithStipend) params.set('min_stipend', '1');
    if (filters.durationMax && filters.durationMax < 12) params.set('max_duration', String(filters.durationMax));

    const resp = await fetch(`${getApiUrl('/supabase/latest-jobs')}?${params.toString()}`, {
      headers: getHeaders(),
    });

    if (!resp.ok) throw new Error(`API error: ${resp.status}`);
    const data = await resp.json();
    if (!data.success) throw new Error(data.error || 'API error');

    const items: Internship[] = (data.data || []).map((item: any) => ensureInternshipFields(item));
    return {
      success: true,
      data: items,
      meta: {
        total: data.meta?.total || items.length,
        page: data.meta?.page || page,
        pageSize: data.meta?.pageSize || pageSize,
        hasMore: data.meta?.hasMore || false,
        filters: filters as FilterState,
        sort: sort as any,
      },
      timestamp: data.timestamp || new Date().toISOString(),
    };
  } catch (error) {
    console.warn('[API] fetchSupabaseLatestJobs failed:', error);
    return {
      success: true, data: [],
      meta: { total: 0, page, pageSize, hasMore: false, filters: filters as FilterState, sort: sort as any },
      timestamp: new Date().toISOString(),
    };
  }
}

export async function fetchSupabaseAllJobs(
  page: number = 1,
  pageSize: number = ITEMS_PER_PAGE,
  filters: Partial<FilterState> = {},
  sort: string = 'date',
  appliedOnly: boolean = false
): Promise<PaginatedResponse<Internship>> {
  try {
    const params = new URLSearchParams();
    params.set('page', String(page));
    params.set('per_page', String(pageSize));
    params.set('sort', sort);
    if (appliedOnly) params.set('applied', 'true');

    if (filters.sources?.length) params.set('source', filters.sources.join(','));
    if (filters.categories?.length) params.set('category', filters.categories.join(','));
    if (filters.locations?.length) params.set('location', filters.locations.join(','));
    if (filters.search) params.set('search', filters.search);
    if (filters.onlyWithStipend) params.set('min_stipend', '1');
    if (filters.durationMax && filters.durationMax < 12) params.set('max_duration', String(filters.durationMax));

    const resp = await fetch(`${getApiUrl('/supabase/all-jobs')}?${params.toString()}`, {
      headers: getHeaders(),
    });

    if (!resp.ok) throw new Error(`API error: ${resp.status}`);
    const data = await resp.json();
    if (!data.success) throw new Error(data.error || 'API error');

    const items: Internship[] = (data.data || []).map((item: any) => ensureInternshipFields(item));
    return {
      success: true,
      data: items,
      meta: {
        total: data.meta?.total || items.length,
        page: data.meta?.page || page,
        pageSize: data.meta?.pageSize || pageSize,
        hasMore: data.meta?.hasMore || false,
        filters: filters as FilterState,
        sort: sort as any,
      },
      timestamp: data.timestamp || new Date().toISOString(),
    };
  } catch (error) {
    console.warn('[API] fetchSupabaseAllJobs failed:', error);
    return {
      success: true, data: [],
      meta: { total: 0, page, pageSize, hasMore: false, filters: filters as FilterState, sort: sort as any },
      timestamp: new Date().toISOString(),
    };
  }
}

export async function applyToSupabaseJob(id: string, notes: string = ''): Promise<APIResponse<{ status: ApplicationStatus }>> {
  try {
    const resp = await fetch(getApiUrl(`/supabase/apply/${id}`), {
      method: 'POST',
      headers: getHeaders(),
      body: JSON.stringify({ notes }),
    });

    if (!resp.ok) throw new Error(`API error: ${resp.status}`);
    const data = await resp.json();
    return {
      success: data.success,
      data: { status: data.success ? 'applied' : 'not_applied' },
      error: data.error,
      timestamp: data.timestamp || new Date().toISOString(),
    };
  } catch (error) {
    return {
      success: false,
      data: { status: 'not_applied' },
      error: 'Failed to mark as applied',
      timestamp: new Date().toISOString(),
    };
  }
}

export async function fetchSupabaseStats(): Promise<APIResponse<any>> {
  try {
    const resp = await fetch(getApiUrl('/supabase/stats'), { headers: getHeaders() });
    if (!resp.ok) throw new Error(`API error: ${resp.status}`);
    const data = await resp.json();
    return { success: data.success, data: data.data, timestamp: data.timestamp || new Date().toISOString() };
  } catch (error) {
    return { success: false, data: null, timestamp: new Date().toISOString() };
  }
}

// ===== CANONICAL JOB COUNT =====
// Single source of truth for job count across ALL surfaces.
// Call this from Header, Profile, Settings — everywhere you show a count.
export async function fetchCanonicalCount(): Promise<APIResponse<{
  canonical_count: number;
  sqlite_count: number;
  supabase_count: number;
}>> {
  try {
    const resp = await fetch(getApiUrl('/canonical-count'), { headers: getHeaders() });
    if (!resp.ok) throw new Error(`API error: ${resp.status}`);
    const data = await resp.json();
    return {
      success: data.success,
      data: data.data,
      timestamp: data.timestamp || new Date().toISOString(),
    };
  } catch (error) {
    return {
      success: false,
      data: { canonical_count: 0, sqlite_count: 0, supabase_count: 0 },
      timestamp: new Date().toISOString(),
    };
  }
}

// ===== SYSTEM HEALTH CHECK =====
export async function fetchSystemHealth(): Promise<APIResponse<{
  backend: boolean;
  supabase: { connected: boolean; latency_ms?: number; error?: string };
  ai: boolean;
  database: boolean;
  version: string;
}>> {
  try {
    const resp = await fetch(getApiUrl('/system/health'), { headers: getHeaders() });
    if (!resp.ok) throw new Error(`API error: ${resp.status}`);
    const data = await resp.json();
    return {
      success: data.success,
      data: data.data,
      timestamp: data.timestamp || new Date().toISOString(),
    };
  } catch (error) {
    return {
      success: false,
      data: {
        backend: false,
        supabase: { connected: false, error: 'Backend unreachable' },
        ai: false,
        database: false,
        version: 'unknown',
      },
      timestamp: new Date().toISOString(),
    };
  }
}

// ===== FIELD NORMALIZER =====
function ensureInternshipFields(item: any): Internship {
  return {
    id: String(item.id || ''),
    title: item.title || 'Unknown Position',
    company: item.company || 'Unknown Company',
    companyLogo: item.companyLogo || undefined,
    companySize: item.companySize || '',
    companyRating: item.companyRating || 0,
    source: (item.source || 'internshala').toLowerCase(),
    sourceUrl: item.sourceUrl || '',
    stipend: item.stipend || 0,
    stipendCurrency: item.stipendCurrency || '₹',
    stipendType: item.stipendType || (item.stipend > 0 ? 'monthly' : 'unpaid'),
    duration: item.duration || 0,
    durationUnit: item.durationUnit || 'months',
    location: item.location || 'Not specified',
    locationType: item.locationType || 'onsite',
    category: item.category || 'general',
    skills: item.skills || [],
    description: item.description || '',
    responsibilities: item.responsibilities || [],
    requirements: item.requirements || [],
    perks: item.perks || [],
    openings: item.openings || 1,
    applicants: item.applicants || 0,
    postedDate: item.postedDate || new Date().toISOString(),
    deadline: item.deadline || '',
    startDate: item.startDate || '',
    isExpired: item.isExpired || false,
    isPremium: item.isPremium || false,
    isVerified: item.isVerified !== false,
    matchScore: item.matchScore || 50,
    ghostScore: item.ghostScore || 0,
    successRate: item.successRate || 50,
    avgResponseDays: item.avgResponseDays || 5,
    alreadyApplied: item.alreadyApplied || false,
    companyTier: item.companyTier || 'startup',
    sector: item.sector || '',
    tags: item.tags || [],
    lastUpdated: item.lastUpdated || new Date().toISOString(),
    hash: item.hash || generateHash(item.title || '', item.company || '', item.location || ''),
  };
}

// ===== FALLBACK: Offline placeholder when backend is down =====

function fallbackFetchInternships(
  page: number,
  pageSize: number,
  filters: FilterState,
  sort: SortField
): PaginatedResponse<Internship> {
  return {
    success: true,
    data: [],
    meta: {
      total: 0,
      page,
      pageSize,
      hasMore: false,
      filters,
      sort,
    },
    timestamp: new Date().toISOString(),
  };
}

function fallbackFetchAnalytics(): APIResponse<AnalyticsData> {
  return {
    success: true,
    data: {
      totalListings: 0,
      totalApplied: 0,
      totalShortlisted: 0,
      totalRejected: 0,
      totalOffers: 0,
      successRate: 0,
      avgResponseTime: 0,
      topSources: [],
      topCategories: [],
      applicationTimeline: [],
      stipendDistribution: [],
      weeklyActivity: [],
    },
    timestamp: new Date().toISOString(),
  };
}
