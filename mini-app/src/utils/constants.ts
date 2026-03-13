// ============================================================
// INTERNSHIP HUB — CONSTANTS & CONFIGURATION
// ============================================================

import type { SortOption, FilterState, BatchConfig, CredentialRequirement, InternshipSource } from '@/types';

// ===== DEFAULT FILTERS (Auto-applied: highest stipend, ≤3 months) =====
export const DEFAULT_FILTERS: FilterState = {
  search: '',
  sources: [],
  categories: [],
  locations: [],
  locationTypes: [],
  stipendMin: 0,
  stipendMax: 100000,
  stipendType: [],
  durationMin: 0,
  durationMax: 3,
  skills: [],
  companyTiers: [],
  sectors: [],
  minOpenings: 0,
  minMatchScore: 0,
  maxGhostScore: 100,
  hideApplied: true,
  hideExpired: true,
  onlyVerified: false,
  onlyPremium: false,
  onlyWithStipend: true,
  postedWithin: 'any',
  deadlineWithin: 'any',
  successRateMin: 0,
  tags: [],
};

// ===== DEFAULT SORT: Highest Stipend =====
export const DEFAULT_SORT = 'stipend_high' as const;

// ===== ALL SORT OPTIONS =====
export const SORT_OPTIONS: SortOption[] = [
  { field: 'stipend_high', label: 'Highest Stipend', icon: '💰', description: 'Best paying first' },
  { field: 'stipend_low', label: 'Lowest Stipend', icon: '💵', description: 'Budget-friendly first' },
  { field: 'duration_short', label: 'Shortest Duration', icon: '⚡', description: 'Quick internships first' },
  { field: 'duration_long', label: 'Longest Duration', icon: '📅', description: 'Extended internships first' },
  { field: 'match_score', label: 'Best Match', icon: 'target', description: 'AI-matched to your profile' },
  { field: 'success_rate', label: 'Highest Success Rate', icon: '✅', description: 'Best chance of selection' },
  { field: 'posted_recent', label: 'Most Recent', icon: '🆕', description: 'Newly posted first' },
  { field: 'posted_oldest', label: 'Oldest First', icon: '📆', description: 'Longest available first' },
  { field: 'deadline_soon', label: 'Deadline Soon', icon: '⏰', description: 'Urgent applications first' },
  { field: 'deadline_later', label: 'Deadline Later', icon: '🕐', description: 'More time to apply' },
  { field: 'applicants_low', label: 'Fewest Applicants', icon: '👥', description: 'Less competition' },
  { field: 'applicants_high', label: 'Most Popular', icon: '🔥', description: 'Trending internships' },
  { field: 'openings_high', label: 'Most Openings', icon: '🚪', description: 'Higher chance of selection' },
  { field: 'company_rating', label: 'Top Companies', icon: 'star', description: 'Highest rated companies' },
  { field: 'ghost_score_low', label: 'Most Genuine', icon: '🛡️', description: 'Least likely ghost postings' },
  { field: 'response_time', label: 'Fastest Response', icon: '📨', description: 'Quick responders first' },
];

// ===== INTERNSHIP CATEGORIES =====
export const CATEGORIES = [
  'Marketing', 'Finance', 'Operations', 'Human Resources', 'Sales',
  'Consulting', 'Strategy', 'Business Development', 'Product Management',
  'Data Analytics', 'Supply Chain', 'Brand Management', 'Digital Marketing',
  'Investment Banking', 'Private Equity', 'Venture Capital', 'Real Estate',
  'Healthcare Management', 'E-commerce', 'Entrepreneurship', 'Project Management',
  'Research & Development', 'Corporate Finance', 'Risk Management',
  'Sustainability', 'Social Media', 'Content Marketing', 'Public Relations',
  'Event Management', 'Legal', 'IT/Software', 'Design', 'Engineering',
  'Media', 'Education', 'NGO/Non-profit', 'Government',
];

// ===== LOCATION OPTIONS =====
export const LOCATIONS = [
  'Mumbai', 'Delhi', 'Bangalore', 'Hyderabad', 'Chennai',
  'Pune', 'Kolkata', 'Ahmedabad', 'Gurgaon', 'Noida',
  'Jaipur', 'Lucknow', 'Chandigarh', 'Indore', 'Kochi',
  'Bhopal', 'Coimbatore', 'Nagpur', 'Vizag', 'Surat',
  'Work from Home', 'Pan India', 'International',
];

// ===== SKILLS =====
export const POPULAR_SKILLS = [
  'Excel', 'SQL', 'Python', 'Financial Modeling', 'PowerPoint',
  'Data Analysis', 'Market Research', 'SEO', 'Google Analytics',
  'Social Media Marketing', 'Content Writing', 'Tableau', 'R',
  'Java', 'JavaScript', 'React', 'Machine Learning', 'Power BI',
  'Salesforce', 'SAP', 'Adobe Suite', 'Figma', 'AutoCAD',
  'SPSS', 'Bloomberg', 'Tally', 'Communication', 'Leadership',
  'Problem Solving', 'Teamwork', 'Presentation', 'Negotiation',
];

// ===== SECTORS =====
export const SECTORS = [
  'Technology', 'BFSI', 'Consulting', 'FMCG', 'Healthcare',
  'Manufacturing', 'Retail', 'E-commerce', 'Education', 'Media',
  'Real Estate', 'Automotive', 'Energy', 'Telecom', 'Pharma',
  'Logistics', 'Travel & Hospitality', 'Agriculture', 'Fintech',
  'EdTech', 'HealthTech', 'D2C', 'SaaS', 'Government', 'NGO',
];

// ===== SOURCE DISPLAY CONFIG =====
export const SOURCE_CONFIG: Record<InternshipSource, {
  name: string;
  color: string;
  icon: string;
  maxBatchSize: number;
  cooldownMinutes: number;
  riskLevel: 'low' | 'medium' | 'high' | 'critical';
}> = {
  internshala: {
    name: 'Internshala',
    color: '#00bcd4',
    icon: 'internshala',
    maxBatchSize: 5,
    cooldownMinutes: 15,
    riskLevel: 'low',
  },
  linkedin: {
    name: 'LinkedIn',
    color: '#0077b5',
    icon: 'linkedin',
    maxBatchSize: 3,
    cooldownMinutes: 30,
    riskLevel: 'high',
  },
  naukri: {
    name: 'Naukri',
    color: '#4a90d9',
    icon: 'naukri',
    maxBatchSize: 5,
    cooldownMinutes: 15,
    riskLevel: 'medium',
  },
  indeed: {
    name: 'Indeed',
    color: '#2164f3',
    icon: 'indeed',
    maxBatchSize: 5,
    cooldownMinutes: 20,
    riskLevel: 'medium',
  },
  glassdoor: {
    name: 'Glassdoor',
    color: '#0caa41',
    icon: 'glassdoor',
    maxBatchSize: 3,
    cooldownMinutes: 25,
    riskLevel: 'high',
  },
  angellist: {
    name: 'AngelList',
    color: '#000000',
    icon: 'angellist',
    maxBatchSize: 5,
    cooldownMinutes: 15,
    riskLevel: 'low',
  },
  unstop: {
    name: 'Unstop',
    color: '#ff6b00',
    icon: 'unstop',
    maxBatchSize: 5,
    cooldownMinutes: 10,
    riskLevel: 'low',
  },
  letsintern: {
    name: "LetsIntern",
    color: '#e91e63',
    icon: 'letsintern',
    maxBatchSize: 5,
    cooldownMinutes: 10,
    riskLevel: 'low',
  },
  iimjobs: {
    name: 'IIMJobs',
    color: '#ff5722',
    icon: 'iimjobs',
    maxBatchSize: 3,
    cooldownMinutes: 20,
    riskLevel: 'medium',
  },
  freshersworld: {
    name: 'FreshersWorld',
    color: '#4caf50',
    icon: 'freshersworld',
    maxBatchSize: 5,
    cooldownMinutes: 10,
    riskLevel: 'low',
  },
  hirect: {
    name: 'Hirect',
    color: '#673ab7',
    icon: 'hirect',
    maxBatchSize: 3,
    cooldownMinutes: 15,
    riskLevel: 'medium',
  },
  cutshort: {
    name: 'CutShort',
    color: '#795548',
    icon: 'cutshort',
    maxBatchSize: 3,
    cooldownMinutes: 15,
    riskLevel: 'medium',
  },
  wellfound: {
    name: 'Wellfound',
    color: '#000000',
    icon: 'wellfound',
    maxBatchSize: 3,
    cooldownMinutes: 20,
    riskLevel: 'medium',
  },
  foundit: {
    name: 'Foundit',
    color: '#ff9800',
    icon: 'foundit',
    maxBatchSize: 5,
    cooldownMinutes: 15,
    riskLevel: 'low',
  },
  shine: {
    name: 'Shine',
    color: '#9c27b0',
    icon: 'shine',
    maxBatchSize: 5,
    cooldownMinutes: 10,
    riskLevel: 'low',
  },
  apna: {
    name: 'Apna',
    color: '#3f51b5',
    icon: 'apna',
    maxBatchSize: 5,
    cooldownMinutes: 10,
    riskLevel: 'low',
  },
  company_direct: {
    name: 'Company Direct',
    color: '#607d8b',
    icon: 'company_direct',
    maxBatchSize: 2,
    cooldownMinutes: 30,
    riskLevel: 'high',
  },
};

// ===== CREDENTIAL REQUIREMENTS =====
export const CREDENTIAL_REQUIREMENTS: CredentialRequirement[] = [
  {
    source: 'internshala',
    fields: [
      { key: 'email', label: 'Email', type: 'email', required: true, placeholder: 'your@email.com', helpText: 'Registered Internshala email' },
      { key: 'password', label: 'Password', type: 'password', required: true, placeholder: '••••••••' },
    ],
    loginUrl: 'https://internshala.com/login',
    notes: 'Use your Internshala account. Ensure profile is 100% complete for best results.',
  },
  {
    source: 'linkedin',
    fields: [
      { key: 'email', label: 'Email / Phone', type: 'text', required: true, placeholder: 'email or phone' },
      { key: 'password', label: 'Password', type: 'password', required: true, placeholder: '••••••••' },
    ],
    loginUrl: 'https://linkedin.com/login',
    notes: 'LinkedIn has strict rate limits. Use with caution. Enable 2FA recommended.',
  },
  {
    source: 'naukri',
    fields: [
      { key: 'email', label: 'Email', type: 'email', required: true, placeholder: 'your@email.com' },
      { key: 'password', label: 'Password', type: 'password', required: true, placeholder: '••••••••' },
    ],
    loginUrl: 'https://naukri.com/nlogin/login',
    notes: 'Naukri may require OTP verification. Keep your phone nearby.',
  },
  {
    source: 'unstop',
    fields: [
      { key: 'email', label: 'Email', type: 'email', required: true, placeholder: 'your@email.com' },
      { key: 'password', label: 'Password', type: 'password', required: true, placeholder: '••••••••' },
    ],
    loginUrl: 'https://unstop.com/auth/login',
    notes: 'Unstop account with complete profile preferred.',
  },
  {
    source: 'indeed',
    fields: [
      { key: 'email', label: 'Email', type: 'email', required: true, placeholder: 'your@email.com' },
      { key: 'password', label: 'Password', type: 'password', required: true, placeholder: '••••••••' },
      { key: 'resume', label: 'Resume PDF', type: 'file', required: false, placeholder: 'Upload PDF', helpText: 'Optional: Auto-attach to applications' },
    ],
    loginUrl: 'https://indeed.com/account/login',
    notes: 'Upload resume on Indeed for one-click apply support.',
  },
];

// ===== BATCH CONFIGURATION =====
export const BATCH_DEFAULTS: BatchConfig = {
  maxPerBatch: 5,
  cooldownMinutes: 15,
  sourceLimit: null,
  requiresCredentials: CREDENTIAL_REQUIREMENTS,
  securityLevel: 'medium',
  riskWarning: 'Auto-applying uses your credentials to submit applications on your behalf. Ensure your profile is complete and accurate. Rate limits are enforced to protect your account.',
};

// ===== SECURITY RISK WARNINGS =====
export const RISK_WARNINGS: Record<string, string> = {
  low: 'This source has lenient rate limits. Safe for batch applications.',
  medium: 'Moderate rate limits in place. Cooldown periods will be enforced between batches.',
  high: 'Strict rate limiting detected. Limited batch sizes to prevent account flags. Use with caution.',
  critical: 'This source actively detects automation. Manual application recommended. Account suspension risk exists.',
};

// ===== COMPANY TIERS =====
export const TIER_LABELS: Record<string, { label: string; color: string; icon: string }> = {
  tier1: { label: 'Tier 1 Elite', color: '#f59e0b', icon: 'tier1' },
  tier2: { label: 'Tier 2 MNC', color: '#8b5cf6', icon: 'tier2' },
  tier3: { label: 'Tier 3 Growth', color: '#3b82f6', icon: 'tier3' },
  startup: { label: 'Startup', color: '#22c55e', icon: 'wellfound' },
  mnc: { label: 'MNC', color: '#ef4444', icon: 'mnc' },
  govt: { label: 'Government', color: '#14b8a6', icon: 'company_direct' },
  ngo: { label: 'NGO', color: '#ec4899', icon: 'ngo' },
};

// ===== POSTED WITHIN OPTIONS =====
export const POSTED_WITHIN_OPTIONS = [
  { value: 'any', label: 'Any time' },
  { value: '24h', label: 'Last 24 hours' },
  { value: '3d', label: 'Last 3 days' },
  { value: '7d', label: 'Last week' },
  { value: '14d', label: 'Last 2 weeks' },
  { value: '30d', label: 'Last month' },
];

// ===== STIPEND RANGES =====
export const STIPEND_RANGES = [
  { min: 0, max: 5000, label: '₹0 - ₹5K' },
  { min: 5000, max: 10000, label: '₹5K - ₹10K' },
  { min: 10000, max: 20000, label: '₹10K - ₹20K' },
  { min: 20000, max: 35000, label: '₹20K - ₹35K' },
  { min: 35000, max: 50000, label: '₹35K - ₹50K' },
  { min: 50000, max: 100000, label: '₹50K+' },
];

// ===== API CONFIG =====
export const API_BASE_URL = '/api';
export const ITEMS_PER_PAGE = 20;
export const MAX_SELECTION = 50;
export const DEDUP_CHECK_INTERVAL = 60_000; // 1 min
