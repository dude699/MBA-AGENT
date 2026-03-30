// ============================================================
// INTERNSHIP HUB — COMPLETE TYPE DEFINITIONS
// ============================================================

// ===== INTERNSHIP SOURCES =====
export type InternshipSource =
  | 'internshala'
  | 'linkedin'
  | 'naukri'
  | 'indeed'
  | 'glassdoor'
  | 'angellist'
  | 'unstop'
  | 'letsintern'
  | 'iimjobs'
  | 'freshersworld'
  | 'hirect'
  | 'cutshort'
  | 'wellfound'
  | 'foundit'
  | 'shine'
  | 'apna'
  | 'company_direct'
  | 'greenhouse'
  | 'lever'
  | 'instahyre'
  | 'workday'
  | 'smartrecruiters'
  | 'ashby'
  | 'careerpage'
  | string;

// ===== CORE INTERNSHIP =====
export interface Internship {
  id: string;
  title: string;
  company: string;
  companyLogo?: string;
  companySize?: string;
  companyRating?: number;
  source: InternshipSource;
  sourceUrl: string;
  stipend: number;
  stipendCurrency: string;
  stipendType: 'monthly' | 'lumpsum' | 'performance' | 'unpaid';
  duration: number; // months
  durationUnit: 'months' | 'weeks' | 'days';
  location: string;
  locationType: 'remote' | 'onsite' | 'hybrid';
  category: string;
  skills: string[];
  description: string;
  responsibilities: string[];
  requirements: string[];
  perks: string[];
  openings: number;
  applicants: number;
  postedDate: string;
  deadline: string;
  startDate?: string;
  isExpired: boolean;
  isPremium: boolean;
  isVerified: boolean;
  matchScore: number; // 0-100 AI match score
  ghostScore: number; // 0-100 likelihood of ghost posting
  successRate: number; // historical success rate %
  avgResponseDays: number;
  alreadyApplied: boolean;
  appliedDate?: string;
  applicationStatus?: ApplicationStatus;
  companyTier: CompanyTier;
  sector: string;
  tags: string[];
  lastUpdated: string;
  hash: string; // dedup hash
}

// ===== APPLICATION STATUS =====
export type ApplicationStatus =
  | 'not_applied'
  | 'queued'
  | 'applying'
  | 'applied'
  | 'viewed'
  | 'shortlisted'
  | 'interview'
  | 'rejected'
  | 'offer'
  | 'withdrawn';

export type CompanyTier = 'tier1' | 'tier2' | 'tier3' | 'startup' | 'mnc' | 'govt' | 'ngo';

// ===== FILTER STATE =====
export interface FilterState {
  search: string;
  sources: InternshipSource[];
  categories: string[];
  locations: string[];
  locationTypes: ('remote' | 'onsite' | 'hybrid')[];
  stipendMin: number;
  stipendMax: number;
  stipendType: ('monthly' | 'lumpsum' | 'performance' | 'unpaid')[];
  durationMin: number;
  durationMax: number;
  skills: string[];
  companyTiers: CompanyTier[];
  sectors: string[];
  minOpenings: number;
  minMatchScore: number;
  maxGhostScore: number;
  hideApplied: boolean;
  hideExpired: boolean;
  onlyVerified: boolean;
  onlyPremium: boolean;
  onlyWithStipend: boolean;
  postedWithin: 'any' | '24h' | '3d' | '7d' | '14d' | '30d';
  deadlineWithin: 'any' | '3d' | '7d' | '14d' | '30d';
  successRateMin: number;
  tags: string[];
}

// ===== SORT OPTIONS =====
export type SortField =
  | 'stipend_high'
  | 'stipend_low'
  | 'duration_short'
  | 'duration_long'
  | 'match_score'
  | 'success_rate'
  | 'posted_recent'
  | 'posted_oldest'
  | 'deadline_soon'
  | 'deadline_later'
  | 'applicants_low'
  | 'applicants_high'
  | 'openings_high'
  | 'company_rating'
  | 'ghost_score_low'
  | 'response_time';

export interface SortOption {
  field: SortField;
  label: string;
  icon: string;
  description: string;
}

// ===== BATCH APPLY =====
export interface BatchConfig {
  maxPerBatch: number;
  cooldownMinutes: number;
  sourceLimit: InternshipSource | null;
  requiresCredentials: CredentialRequirement[];
  securityLevel: 'low' | 'medium' | 'high' | 'critical';
  riskWarning: string;
}

export interface CredentialRequirement {
  source: InternshipSource;
  fields: CredentialField[];
  loginUrl: string;
  notes: string;
}

export interface CredentialField {
  key: string;
  label: string;
  type: 'text' | 'password' | 'email' | 'phone' | 'file';
  required: boolean;
  placeholder: string;
  helpText?: string;
}

// ===== BATCH STATE =====
export interface BatchState {
  id: string;
  status: 'idle' | 'preparing' | 'running' | 'paused' | 'completed' | 'failed' | 'cooldown';
  source: InternshipSource | null;
  selectedIds: string[];
  processedIds: string[];
  failedIds: string[];
  currentIndex: number;
  totalCount: number;
  startedAt?: string;
  completedAt?: string;
  cooldownEndsAt?: string;
  nextBatchUnlocksAt?: string;
  errors: BatchError[];
  successCount: number;
  failCount: number;
  // v4.0: Manual apply links (rendered as clickable <a> tags, not window.open)
  manualApplyLinks?: Array<{ id: string; url: string; title: string; company: string }>;
  manualNeededCount?: number;
  // v4.0: Assisted apply links with AI-generated cover letters
  assistedApplyLinks?: Array<{ id: string; url: string; title: string; company: string; coverLetter: string }>;
}

export interface BatchError {
  internshipId: string;
  error: string;
  timestamp: string;
  retryable: boolean;
}

// ===== LLM INTEGRATION =====
export interface LLMMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: string;
  metadata?: {
    model?: string;
    tokensUsed?: number;
    internshipIds?: string[];
    action?: LLMAction;
    provider?: string;
    profile?: string;
  };
}

export type LLMAction =
  | 'analyze_listing'
  | 'compare_internships'
  | 'generate_cover_letter'
  | 'optimize_profile'
  | 'suggest_filters'
  | 'risk_assessment'
  | 'interview_prep'
  | 'general_chat';

// ===== ANALYTICS =====
export interface AnalyticsData {
  totalListings: number;
  totalApplied: number;
  totalShortlisted: number;
  totalRejected: number;
  totalOffers: number;
  successRate: number;
  avgResponseTime: number;
  topSources: SourceStat[];
  topCategories: CategoryStat[];
  applicationTimeline: TimelineEntry[];
  stipendDistribution: StipendBucket[];
  weeklyActivity: WeeklyActivity[];
}

export interface SourceStat {
  source: InternshipSource;
  count: number;
  applied: number;
  successRate: number;
}

export interface CategoryStat {
  category: string;
  count: number;
  avgStipend: number;
}

export interface TimelineEntry {
  date: string;
  applied: number;
  shortlisted: number;
  rejected: number;
  offers: number;
}

export interface StipendBucket {
  range: string;
  count: number;
  min: number;
  max: number;
}

export interface WeeklyActivity {
  week: string;
  applications: number;
  responses: number;
}

// ===== CREDENTIALS STORE =====
export interface SourceCredentials {
  source: InternshipSource;
  credentials: Record<string, string>;
  isValid: boolean;
  lastVerified?: string;
  expiresAt?: string;
}

// ===== USER PREFERENCES =====
export interface UserPreferences {
  defaultSort: SortField;
  defaultFilters: Partial<FilterState>;
  autoApplyDefaults: {
    maxStipend: boolean;
    maxDuration: number;
    preferredSources: InternshipSource[];
    batchSize: number;
  };
  notifications: {
    newListings: boolean;
    applicationUpdates: boolean;
    batchComplete: boolean;
    deadlineReminders: boolean;
  };
  theme: 'light' | 'dark' | 'auto';
  compactView: boolean;
}

// ===== API RESPONSES =====
export interface APIResponse<T> {
  success: boolean;
  data: T;
  meta?: {
    total: number;
    page: number;
    pageSize: number;
    hasMore: boolean;
    filters: FilterState;
    sort: SortField;
  };
  error?: string;
  timestamp: string;
}

export interface PaginatedResponse<T> extends APIResponse<T[]> {
  meta: {
    total: number;
    page: number;
    pageSize: number;
    hasMore: boolean;
    filters: FilterState;
    sort: SortField;
  };
}

// ===== TELEGRAM WEB APP =====
export interface TelegramWebApp {
  ready: () => void;
  expand: () => void;
  close: () => void;
  setHeaderColor: (color: string) => void;
  setBackgroundColor: (color: string) => void;
  enableClosingConfirmation: () => void;
  disableClosingConfirmation: () => void;
  showPopup: (params: any) => void;
  showAlert: (message: string) => void;
  showConfirm: (message: string, callback: (confirmed: boolean) => void) => void;
  MainButton: {
    text: string;
    color: string;
    textColor: string;
    isVisible: boolean;
    isActive: boolean;
    show: () => void;
    hide: () => void;
    enable: () => void;
    disable: () => void;
    setText: (text: string) => void;
    onClick: (callback: () => void) => void;
    offClick: (callback: () => void) => void;
    showProgress: (leaveActive: boolean) => void;
    hideProgress: () => void;
  };
  BackButton: {
    isVisible: boolean;
    show: () => void;
    hide: () => void;
    onClick: (callback: () => void) => void;
    offClick: (callback: () => void) => void;
  };
  HapticFeedback: {
    impactOccurred: (style: 'light' | 'medium' | 'heavy' | 'rigid' | 'soft') => void;
    notificationOccurred: (type: 'error' | 'success' | 'warning') => void;
    selectionChanged: () => void;
  };
  initData: string;
  initDataUnsafe: {
    user?: {
      id: number;
      first_name: string;
      last_name?: string;
      username?: string;
      language_code?: string;
    };
    chat_instance?: string;
    chat_type?: string;
    start_param?: string;
  };
  colorScheme: 'light' | 'dark';
  themeParams: Record<string, string>;
  viewportHeight: number;
  viewportStableHeight: number;
}

declare global {
  interface Window {
    Telegram?: {
      WebApp: TelegramWebApp;
    };
  }
}

export {};
