// ============================================================
// INTERNSHIP HUB — UTILITY HELPERS
// ============================================================

import { format, formatDistanceToNow, parseISO, isAfter, isBefore, addDays } from 'date-fns';
import type { Internship, FilterState, SortField } from '@/types';

// ===== FORMATTING =====
export function formatStipend(amount: number, currency: string = '₹'): string {
  if (amount === 0) return 'Unpaid';
  if (amount >= 100000) return `${currency}${(amount / 100000).toFixed(1)}L/mo`;
  if (amount >= 1000) return `${currency}${(amount / 1000).toFixed(amount % 1000 === 0 ? 0 : 1)}K/mo`;
  return `${currency}${amount}/mo`;
}

export function formatDuration(months: number): string {
  if (months === 0) return 'Flexible';
  if (months === 1) return '1 month';
  if (months < 1) return `${Math.round(months * 4)} weeks`;
  return `${months} months`;
}

export function formatNumber(num: number): string {
  if (num >= 1000000) return `${(num / 1000000).toFixed(1)}M`;
  if (num >= 1000) return `${(num / 1000).toFixed(num >= 10000 ? 0 : 1)}K`;
  return num.toString();
}

export function formatDate(dateStr: string): string {
  try {
    return format(parseISO(dateStr), 'MMM d, yyyy');
  } catch {
    return dateStr;
  }
}

export function formatRelativeDate(dateStr: string): string {
  try {
    return formatDistanceToNow(parseISO(dateStr), { addSuffix: true });
  } catch {
    return dateStr;
  }
}

export function formatDeadline(dateStr: string): { text: string; urgent: boolean; expired: boolean } {
  try {
    const date = parseISO(dateStr);
    const now = new Date();
    if (isBefore(date, now)) return { text: 'Expired', urgent: false, expired: true };
    const daysLeft = Math.ceil((date.getTime() - now.getTime()) / (1000 * 60 * 60 * 24));
    if (daysLeft <= 2) return { text: `${daysLeft}d left`, urgent: true, expired: false };
    if (daysLeft <= 7) return { text: `${daysLeft} days left`, urgent: true, expired: false };
    return { text: format(date, 'MMM d'), urgent: false, expired: false };
  } catch {
    return { text: dateStr, urgent: false, expired: false };
  }
}

// ===== FILTERING =====
export function applyFilters(internships: Internship[], filters: FilterState): Internship[] {
  if (!filters || !internships) return internships || [];

  return internships.filter((item) => {
    if (!item) return false;

    // Search — null-safe
    if (filters.search) {
      const q = filters.search.toLowerCase();
      const searchable = `${item.title || ''} ${item.company || ''} ${item.category || ''} ${(item.skills || []).join(' ')} ${item.location || ''} ${item.sector || ''}`.toLowerCase();
      if (!searchable.includes(q)) return false;
    }

    // Source filter — case-insensitive
    if (filters.sources?.length > 0) {
      const itemSource = (item.source || '').toLowerCase();
      if (!filters.sources.some(s => s.toLowerCase() === itemSource)) return false;
    }

    // Category filter — case-insensitive
    if (filters.categories?.length > 0) {
      const itemCat = (item.category || '').toLowerCase();
      if (!filters.categories.some(c => c.toLowerCase() === itemCat)) return false;
    }

    // Location filter — case-insensitive PARTIAL match
    // Listings have "Mumbai, Maharashtra" but user selects "Mumbai"
    if (filters.locations?.length > 0) {
      const itemLoc = (item.location || '').toLowerCase();
      if (!filters.locations.some(l => itemLoc.includes(l.toLowerCase()) || l.toLowerCase().includes(itemLoc))) return false;
    }

    // Location type filter — case-insensitive
    if (filters.locationTypes?.length > 0) {
      const itemLocType = (item.locationType || 'onsite').toLowerCase();
      if (!filters.locationTypes.some(t => t.toLowerCase() === itemLocType)) return false;
    }

    // Stipend range
    const stipend = item.stipend || 0;
    if (stipend < (filters.stipendMin || 0)) return false;
    if (stipend > (filters.stipendMax ?? 100000)) return false;

    // Stipend type
    if (filters.stipendType?.length > 0 && !filters.stipendType.includes(item.stipendType)) return false;

    // Duration range
    const duration = item.duration || 0;
    if (duration < (filters.durationMin || 0)) return false;
    if (duration > (filters.durationMax ?? 12)) return false;

    // Skills
    if (filters.skills?.length > 0) {
      const itemSkills = item.skills || [];
      if (itemSkills.length === 0) return false;
      const has = itemSkills.some((s) => filters.skills.includes(s));
      if (!has) return false;
    }

    // Company tier
    if (filters.companyTiers?.length > 0 && !filters.companyTiers.includes(item.companyTier)) return false;

    // Sectors
    if (filters.sectors?.length > 0 && !filters.sectors.includes(item.sector)) return false;

    // Min openings
    if ((item.openings || 0) < (filters.minOpenings || 0)) return false;

    // Min match score
    if ((item.matchScore || 0) < (filters.minMatchScore || 0)) return false;

    // Max ghost score
    if ((item.ghostScore || 0) > (filters.maxGhostScore ?? 100)) return false;

    // Hide applied
    if (filters.hideApplied && item.alreadyApplied) return false;

    // Hide expired
    if (filters.hideExpired && item.isExpired) return false;

    // Only verified
    if (filters.onlyVerified && !item.isVerified) return false;

    // Only premium
    if (filters.onlyPremium && !item.isPremium) return false;

    // Only with stipend
    if (filters.onlyWithStipend && (item.stipend || 0) === 0) return false;

    // Posted within
    if (filters.postedWithin && filters.postedWithin !== 'any') {
      const daysMap: Record<string, number> = { '24h': 1, '3d': 3, '7d': 7, '14d': 14, '30d': 30 };
      const days = daysMap[filters.postedWithin];
      if (days && item.postedDate) {
        try {
          const postedDate = parseISO(item.postedDate);
          const cutoff = addDays(new Date(), -days);
          if (isBefore(postedDate, cutoff)) return false;
        } catch { /* skip */ }
      }
    }

    // Deadline within
    if (filters.deadlineWithin && filters.deadlineWithin !== 'any') {
      const daysMap: Record<string, number> = { '3d': 3, '7d': 7, '14d': 14, '30d': 30 };
      const days = daysMap[filters.deadlineWithin];
      if (days && item.deadline) {
        try {
          const deadline = parseISO(item.deadline);
          const cutoff = addDays(new Date(), days);
          if (isAfter(deadline, cutoff)) return false;
        } catch { /* skip */ }
      }
    }

    // Success rate
    if ((item.successRate || 0) < (filters.successRateMin || 0)) return false;

    // Tags
    if (filters.tags?.length > 0) {
      const itemTags = item.tags || [];
      if (itemTags.length === 0) return false;
      const has = itemTags.some((t) => filters.tags.includes(t));
      if (!has) return false;
    }

    return true;
  });
}

// ===== SORTING =====
export function applySorting(internships: Internship[], sort: SortField): Internship[] {
  const sorted = [...internships];

  switch (sort) {
    case 'stipend_high':
      return sorted.sort((a, b) => b.stipend - a.stipend);
    case 'stipend_low':
      return sorted.sort((a, b) => a.stipend - b.stipend);
    case 'duration_short':
      return sorted.sort((a, b) => a.duration - b.duration);
    case 'duration_long':
      return sorted.sort((a, b) => b.duration - a.duration);
    case 'match_score':
      return sorted.sort((a, b) => b.matchScore - a.matchScore);
    case 'success_rate':
      return sorted.sort((a, b) => b.successRate - a.successRate);
    case 'posted_recent':
      return sorted.sort((a, b) => new Date(b.postedDate).getTime() - new Date(a.postedDate).getTime());
    case 'posted_oldest':
      return sorted.sort((a, b) => new Date(a.postedDate).getTime() - new Date(b.postedDate).getTime());
    case 'deadline_soon':
      return sorted.sort((a, b) => new Date(a.deadline).getTime() - new Date(b.deadline).getTime());
    case 'deadline_later':
      return sorted.sort((a, b) => new Date(b.deadline).getTime() - new Date(a.deadline).getTime());
    case 'applicants_low':
      return sorted.sort((a, b) => a.applicants - b.applicants);
    case 'applicants_high':
      return sorted.sort((a, b) => b.applicants - a.applicants);
    case 'openings_high':
      return sorted.sort((a, b) => b.openings - a.openings);
    case 'company_rating':
      return sorted.sort((a, b) => (b.companyRating || 0) - (a.companyRating || 0));
    case 'ghost_score_low':
      return sorted.sort((a, b) => a.ghostScore - b.ghostScore);
    case 'response_time':
      return sorted.sort((a, b) => a.avgResponseDays - b.avgResponseDays);
    default:
      return sorted;
  }
}

// ===== DEDUPLICATION =====
export function deduplicateInternships(internships: Internship[]): Internship[] {
  const seen = new Set<string>();
  return internships.filter((item) => {
    if (seen.has(item.hash)) return false;
    seen.add(item.hash);
    return true;
  });
}

// ===== HASH GENERATION =====
export function generateHash(title: string, company: string, location: string): string {
  const str = `${title.toLowerCase().trim()}|${company.toLowerCase().trim()}|${location.toLowerCase().trim()}`;
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    const char = str.charCodeAt(i);
    hash = ((hash << 5) - hash) + char;
    hash |= 0;
  }
  return Math.abs(hash).toString(36);
}

// ===== TELEGRAM HELPERS =====
export function getTelegramUser() {
  try {
    return window.Telegram?.WebApp?.initDataUnsafe?.user || null;
  } catch {
    return null;
  }
}

export function hapticFeedback(type: 'light' | 'medium' | 'heavy' = 'light') {
  try {
    window.Telegram?.WebApp?.HapticFeedback?.impactOccurred(type);
  } catch { /* silent */ }
}

export function hapticNotification(type: 'success' | 'warning' | 'error' = 'success') {
  try {
    window.Telegram?.WebApp?.HapticFeedback?.notificationOccurred(type);
  } catch { /* silent */ }
}

export function hapticSelection() {
  try {
    window.Telegram?.WebApp?.HapticFeedback?.selectionChanged();
  } catch { /* silent */ }
}

// ===== REAL AES-256-GCM ENCRYPTION FOR CREDENTIALS =====
// Uses Web Crypto API (available in all modern browsers including Telegram WebView)

const ENCRYPTION_KEY_NAME = 'internhub_enc_key';

async function getOrCreateEncryptionKey(): Promise<CryptoKey> {
  // Try to retrieve existing key from IndexedDB via a simple localStorage reference
  try {
    const stored = localStorage.getItem(ENCRYPTION_KEY_NAME);
    if (stored) {
      const keyData = JSON.parse(stored);
      return await crypto.subtle.importKey(
        'jwk', keyData,
        { name: 'AES-GCM', length: 256 },
        true, ['encrypt', 'decrypt']
      );
    }
  } catch {}

  // Generate new AES-256 key
  const key = await crypto.subtle.generateKey(
    { name: 'AES-GCM', length: 256 },
    true, ['encrypt', 'decrypt']
  );

  // Export and store
  try {
    const exported = await crypto.subtle.exportKey('jwk', key);
    localStorage.setItem(ENCRYPTION_KEY_NAME, JSON.stringify(exported));
  } catch {}

  return key;
}

export async function encryptCredentials(data: Record<string, string>): Promise<string> {
  try {
    const key = await getOrCreateEncryptionKey();
    const iv = crypto.getRandomValues(new Uint8Array(12));
    const plaintext = new TextEncoder().encode(JSON.stringify(data));

    const ciphertext = await crypto.subtle.encrypt(
      { name: 'AES-GCM', iv },
      key, plaintext
    );

    // Combine IV + ciphertext and base64 encode
    const combined = new Uint8Array(iv.length + new Uint8Array(ciphertext).length);
    combined.set(iv);
    combined.set(new Uint8Array(ciphertext), iv.length);

    return btoa(String.fromCharCode(...combined));
  } catch (e) {
    console.warn('Encryption failed, using base64 fallback:', e);
    return btoa(JSON.stringify(data));
  }
}

export async function decryptCredentials(encryptedData: string): Promise<Record<string, string>> {
  try {
    const key = await getOrCreateEncryptionKey();
    const combined = new Uint8Array(
      atob(encryptedData).split('').map(c => c.charCodeAt(0))
    );

    const iv = combined.slice(0, 12);
    const ciphertext = combined.slice(12);

    const plaintext = await crypto.subtle.decrypt(
      { name: 'AES-GCM', iv },
      key, ciphertext
    );

    return JSON.parse(new TextDecoder().decode(plaintext));
  } catch (e) {
    // Fallback: try base64 decode (for legacy data)
    try {
      return JSON.parse(atob(encryptedData));
    } catch {
      return {};
    }
  }
}

// ===== MISC =====
export function classNames(...classes: (string | boolean | undefined | null)[]): string {
  return classes.filter(Boolean).join(' ');
}

export function truncate(str: string, maxLen: number): string {
  if (str.length <= maxLen) return str;
  return str.slice(0, maxLen - 3) + '...';
}

export function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export function getSourceColor(source: string): string {
  const colors: Record<string, string> = {
    internshala: '#00bcd4',
    linkedin: '#0077b5',
    naukri: '#4a90d9',
    indeed: '#2164f3',
    glassdoor: '#0caa41',
    unstop: '#ff6b00',
    default: '#6b7280',
  };
  return colors[source] || colors.default;
}

export function getMatchScoreColor(score: number): string {
  if (score >= 80) return '#22c55e';
  if (score >= 60) return '#f59e0b';
  if (score >= 40) return '#ef4444';
  return '#9ca3af';
}

export function getStipendLevel(stipend: number): 'high' | 'medium' | 'low' {
  if (stipend >= 25000) return 'high';
  if (stipend >= 10000) return 'medium';
  return 'low';
}
