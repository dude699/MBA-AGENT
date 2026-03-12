// ============================================================
// INTERNSHIP HUB — API SERVICE (MOCK + REAL DATA ENGINE)
// ============================================================

import type {
  Internship, FilterState, SortField, PaginatedResponse,
  AnalyticsData, InternshipSource, APIResponse, ApplicationStatus,
} from '@/types';
import { API_BASE_URL, ITEMS_PER_PAGE } from '@/utils/constants';
import { generateHash, applyFilters, applySorting, deduplicateInternships } from '@/utils/helpers';
import { v4 as uuid } from 'uuid';

// ===== COMPANIES DATABASE (1000+) =====
const COMPANIES: { name: string; sector: string; tier: string; logo?: string; rating: number; size: string }[] = [
  // Tier 1 — Top MNCs & Consulting
  { name: 'McKinsey & Company', sector: 'Consulting', tier: 'tier1', rating: 4.8, size: '10000+' },
  { name: 'Boston Consulting Group', sector: 'Consulting', tier: 'tier1', rating: 4.7, size: '10000+' },
  { name: 'Bain & Company', sector: 'Consulting', tier: 'tier1', rating: 4.7, size: '5000+' },
  { name: 'Goldman Sachs', sector: 'BFSI', tier: 'tier1', rating: 4.5, size: '10000+' },
  { name: 'JP Morgan Chase', sector: 'BFSI', tier: 'tier1', rating: 4.4, size: '10000+' },
  { name: 'Morgan Stanley', sector: 'BFSI', tier: 'tier1', rating: 4.4, size: '10000+' },
  { name: 'Google', sector: 'Technology', tier: 'tier1', rating: 4.8, size: '10000+' },
  { name: 'Microsoft', sector: 'Technology', tier: 'tier1', rating: 4.6, size: '10000+' },
  { name: 'Amazon', sector: 'Technology', tier: 'tier1', rating: 4.3, size: '10000+' },
  { name: 'Apple', sector: 'Technology', tier: 'tier1', rating: 4.7, size: '10000+' },
  { name: 'Meta', sector: 'Technology', tier: 'tier1', rating: 4.4, size: '10000+' },
  { name: 'Netflix', sector: 'Media', tier: 'tier1', rating: 4.5, size: '5000+' },
  { name: 'Deloitte', sector: 'Consulting', tier: 'tier1', rating: 4.2, size: '10000+' },
  { name: 'PwC', sector: 'Consulting', tier: 'tier1', rating: 4.1, size: '10000+' },
  { name: 'EY', sector: 'Consulting', tier: 'tier1', rating: 4.1, size: '10000+' },
  { name: 'KPMG', sector: 'Consulting', tier: 'tier1', rating: 4.0, size: '10000+' },
  { name: 'Accenture', sector: 'Technology', tier: 'tier1', rating: 4.0, size: '10000+' },
  { name: 'Unilever', sector: 'FMCG', tier: 'tier1', rating: 4.3, size: '10000+' },
  { name: 'P&G', sector: 'FMCG', tier: 'tier1', rating: 4.4, size: '10000+' },
  { name: 'Nestle', sector: 'FMCG', tier: 'tier1', rating: 4.2, size: '10000+' },
  // Tier 2 — Large Companies
  { name: 'Flipkart', sector: 'E-commerce', tier: 'tier2', rating: 4.1, size: '5000+' },
  { name: 'Swiggy', sector: 'E-commerce', tier: 'tier2', rating: 3.9, size: '5000+' },
  { name: 'Zomato', sector: 'E-commerce', tier: 'tier2', rating: 3.8, size: '5000+' },
  { name: 'Paytm', sector: 'Fintech', tier: 'tier2', rating: 3.7, size: '5000+' },
  { name: 'PhonePe', sector: 'Fintech', tier: 'tier2', rating: 4.0, size: '2000+' },
  { name: 'Razorpay', sector: 'Fintech', tier: 'tier2', rating: 4.2, size: '2000+' },
  { name: 'CRED', sector: 'Fintech', tier: 'tier2', rating: 4.3, size: '1000+' },
  { name: 'Dream11', sector: 'Technology', tier: 'tier2', rating: 4.1, size: '1000+' },
  { name: 'Meesho', sector: 'E-commerce', tier: 'tier2', rating: 3.8, size: '1000+' },
  { name: 'Ola', sector: 'Technology', tier: 'tier2', rating: 3.6, size: '5000+' },
  { name: 'Uber India', sector: 'Technology', tier: 'tier2', rating: 4.0, size: '5000+' },
  { name: 'Byju\'s', sector: 'EdTech', tier: 'tier2', rating: 3.4, size: '10000+' },
  { name: 'Upgrad', sector: 'EdTech', tier: 'tier2', rating: 3.8, size: '2000+' },
  { name: 'Lenskart', sector: 'D2C', tier: 'tier2', rating: 3.9, size: '2000+' },
  { name: 'Nykaa', sector: 'D2C', tier: 'tier2', rating: 3.8, size: '2000+' },
  { name: 'boAt', sector: 'D2C', tier: 'tier2', rating: 3.7, size: '500+' },
  { name: 'Mamaearth', sector: 'D2C', tier: 'tier2', rating: 3.6, size: '500+' },
  { name: 'Groww', sector: 'Fintech', tier: 'tier2', rating: 4.1, size: '1000+' },
  { name: 'Zerodha', sector: 'Fintech', tier: 'tier2', rating: 4.3, size: '500+' },
  { name: 'HDFC Bank', sector: 'BFSI', tier: 'tier2', rating: 3.9, size: '10000+' },
  { name: 'ICICI Bank', sector: 'BFSI', tier: 'tier2', rating: 3.7, size: '10000+' },
  { name: 'Kotak Mahindra', sector: 'BFSI', tier: 'tier2', rating: 3.8, size: '5000+' },
  { name: 'Axis Bank', sector: 'BFSI', tier: 'tier2', rating: 3.6, size: '5000+' },
  { name: 'Reliance Industries', sector: 'Manufacturing', tier: 'tier2', rating: 4.0, size: '10000+' },
  { name: 'Tata Group', sector: 'Manufacturing', tier: 'tier2', rating: 4.2, size: '10000+' },
  { name: 'Mahindra Group', sector: 'Manufacturing', tier: 'tier2', rating: 4.0, size: '10000+' },
  { name: 'Infosys', sector: 'Technology', tier: 'tier2', rating: 3.8, size: '10000+' },
  { name: 'Wipro', sector: 'Technology', tier: 'tier2', rating: 3.6, size: '10000+' },
  { name: 'TCS', sector: 'Technology', tier: 'tier2', rating: 3.7, size: '10000+' },
  { name: 'HCL Tech', sector: 'Technology', tier: 'tier2', rating: 3.5, size: '10000+' },
  // Tier 3 + Startups (extensive list)
  { name: 'Freshworks', sector: 'SaaS', tier: 'tier3', rating: 4.0, size: '2000+' },
  { name: 'Zoho', sector: 'SaaS', tier: 'tier3', rating: 4.1, size: '5000+' },
  { name: 'Chargebee', sector: 'SaaS', tier: 'startup', rating: 4.0, size: '500+' },
  { name: 'Postman', sector: 'SaaS', tier: 'startup', rating: 4.3, size: '500+' },
  { name: 'Clevertap', sector: 'SaaS', tier: 'startup', rating: 3.9, size: '500+' },
  { name: 'Darwinbox', sector: 'SaaS', tier: 'startup', rating: 4.0, size: '500+' },
  { name: 'Druva', sector: 'Technology', tier: 'startup', rating: 4.1, size: '500+' },
  { name: 'BrowserStack', sector: 'Technology', tier: 'startup', rating: 4.2, size: '500+' },
  { name: 'Delhivery', sector: 'Logistics', tier: 'tier3', rating: 3.5, size: '2000+' },
  { name: 'Dunzo', sector: 'Logistics', tier: 'startup', rating: 3.3, size: '500+' },
  { name: 'Urban Company', sector: 'Technology', tier: 'tier3', rating: 3.7, size: '1000+' },
  { name: 'Cars24', sector: 'Automotive', tier: 'tier3', rating: 3.5, size: '1000+' },
  { name: 'Spinny', sector: 'Automotive', tier: 'startup', rating: 3.6, size: '500+' },
  { name: 'Physics Wallah', sector: 'EdTech', tier: 'startup', rating: 3.8, size: '2000+' },
  { name: 'Vedantu', sector: 'EdTech', tier: 'startup', rating: 3.5, size: '1000+' },
  { name: 'Unacademy', sector: 'EdTech', tier: 'tier3', rating: 3.4, size: '2000+' },
  { name: 'ShareChat', sector: 'Media', tier: 'startup', rating: 3.6, size: '1000+' },
  { name: 'Dailyhunt', sector: 'Media', tier: 'startup', rating: 3.4, size: '500+' },
  { name: 'MPL', sector: 'Technology', tier: 'startup', rating: 3.5, size: '500+' },
  { name: 'Pocket FM', sector: 'Media', tier: 'startup', rating: 3.7, size: '500+' },
  { name: 'Cure.fit', sector: 'HealthTech', tier: 'startup', rating: 3.6, size: '1000+' },
  { name: 'Practo', sector: 'HealthTech', tier: 'startup', rating: 3.7, size: '500+' },
  { name: '1mg', sector: 'HealthTech', tier: 'startup', rating: 3.5, size: '500+' },
  { name: 'PharmEasy', sector: 'HealthTech', tier: 'startup', rating: 3.4, size: '1000+' },
  { name: 'BigBasket', sector: 'E-commerce', tier: 'tier3', rating: 3.6, size: '2000+' },
  { name: 'BlinkIt', sector: 'E-commerce', tier: 'tier3', rating: 3.5, size: '1000+' },
  { name: 'Zepto', sector: 'E-commerce', tier: 'startup', rating: 3.8, size: '500+' },
  { name: 'Country Delight', sector: 'D2C', tier: 'startup', rating: 3.6, size: '500+' },
  { name: 'Sugar Cosmetics', sector: 'D2C', tier: 'startup', rating: 3.7, size: '500+' },
  { name: 'mCaffeine', sector: 'D2C', tier: 'startup', rating: 3.5, size: '200+' },
  { name: 'WOW Skin Science', sector: 'D2C', tier: 'startup', rating: 3.4, size: '200+' },
  { name: 'Kapiva', sector: 'D2C', tier: 'startup', rating: 3.3, size: '200+' },
  { name: 'Slice', sector: 'Fintech', tier: 'startup', rating: 3.8, size: '500+' },
  { name: 'Jupiter', sector: 'Fintech', tier: 'startup', rating: 3.7, size: '200+' },
  { name: 'Fi Money', sector: 'Fintech', tier: 'startup', rating: 3.6, size: '200+' },
  { name: 'Pine Labs', sector: 'Fintech', tier: 'tier3', rating: 3.8, size: '500+' },
  { name: 'Simpl', sector: 'Fintech', tier: 'startup', rating: 3.5, size: '200+' },
  { name: 'OYO Rooms', sector: 'Travel & Hospitality', tier: 'tier3', rating: 3.3, size: '5000+' },
  { name: 'MakeMyTrip', sector: 'Travel & Hospitality', tier: 'tier3', rating: 3.8, size: '2000+' },
  { name: 'Ixigo', sector: 'Travel & Hospitality', tier: 'startup', rating: 3.6, size: '500+' },
  { name: 'Cleartrip', sector: 'Travel & Hospitality', tier: 'tier3', rating: 3.5, size: '500+' },
  { name: 'Yatra', sector: 'Travel & Hospitality', tier: 'tier3', rating: 3.4, size: '500+' },
  { name: 'Titan Company', sector: 'Retail', tier: 'tier2', rating: 4.1, size: '5000+' },
  { name: 'Aditya Birla', sector: 'Manufacturing', tier: 'tier2', rating: 3.9, size: '10000+' },
  { name: 'Godrej', sector: 'FMCG', tier: 'tier2', rating: 4.0, size: '5000+' },
  { name: 'ITC Limited', sector: 'FMCG', tier: 'tier2', rating: 4.1, size: '10000+' },
  { name: 'Dabur', sector: 'FMCG', tier: 'tier3', rating: 3.8, size: '5000+' },
  { name: 'Colgate-Palmolive', sector: 'FMCG', tier: 'tier3', rating: 4.0, size: '2000+' },
  { name: 'Asian Paints', sector: 'Manufacturing', tier: 'tier2', rating: 4.2, size: '5000+' },
  { name: 'JSW Group', sector: 'Manufacturing', tier: 'tier3', rating: 3.7, size: '5000+' },
  { name: 'Adani Group', sector: 'Energy', tier: 'tier2', rating: 3.5, size: '10000+' },
  { name: 'Bajaj Finance', sector: 'BFSI', tier: 'tier2', rating: 3.9, size: '5000+' },
  { name: 'SBI', sector: 'BFSI', tier: 'govt', rating: 3.7, size: '10000+' },
  { name: 'RBI', sector: 'BFSI', tier: 'govt', rating: 4.5, size: '10000+' },
  { name: 'NITI Aayog', sector: 'Government', tier: 'govt', rating: 4.3, size: '1000+' },
  { name: 'ISRO', sector: 'Government', tier: 'govt', rating: 4.8, size: '10000+' },
  { name: 'DRDO', sector: 'Government', tier: 'govt', rating: 4.2, size: '10000+' },
  { name: 'UN India', sector: 'NGO', tier: 'ngo', rating: 4.5, size: '1000+' },
  { name: 'WHO India', sector: 'NGO', tier: 'ngo', rating: 4.4, size: '500+' },
  { name: 'Red Cross India', sector: 'NGO', tier: 'ngo', rating: 4.0, size: '500+' },
  { name: 'Teach For India', sector: 'NGO', tier: 'ngo', rating: 4.2, size: '500+' },
];

// Extend to 1000+ by generating realistic variations
function generateExtendedCompanies() {
  const baseSectors = ['Technology', 'BFSI', 'Consulting', 'FMCG', 'Healthcare', 'Manufacturing', 'E-commerce', 'EdTech', 'Fintech', 'SaaS', 'D2C', 'Logistics', 'Media', 'Real Estate', 'Energy', 'Retail', 'Pharma', 'HealthTech', 'Travel & Hospitality', 'Automotive'];
  const prefixes = ['Neo', 'Astra', 'Veda', 'Nova', 'Pulse', 'Apex', 'Zen', 'Orbit', 'Flux', 'Crisp', 'Bolt', 'Leap', 'Core', 'Next', 'Peak', 'Edge', 'Wave', 'Spark', 'Grid', 'Lyra', 'Sage', 'Halo', 'Prism', 'Dyna', 'Kite', 'Fern', 'Opal', 'Quill', 'Rune', 'Wren'];
  const suffixes = ['Tech', 'Labs', 'Works', 'Systems', 'Digital', 'Solutions', 'Global', 'India', 'Corp', 'Group', 'AI', 'Cloud', 'Studio', 'Hub', 'Base', 'Craft', 'Logic', 'Mind', 'Nest', 'Path'];

  const extra: typeof COMPANIES = [];
  for (let i = 0; i < 920; i++) {
    const prefix = prefixes[i % prefixes.length];
    const suffix = suffixes[Math.floor(i / prefixes.length) % suffixes.length];
    const sector = baseSectors[i % baseSectors.length];
    extra.push({
      name: `${prefix}${suffix}`,
      sector,
      tier: i % 5 === 0 ? 'tier3' : 'startup',
      rating: 3.0 + Math.random() * 1.5,
      size: ['50+', '100+', '200+', '500+'][i % 4],
    });
  }
  return [...COMPANIES, ...extra];
}

const ALL_COMPANIES = generateExtendedCompanies();

// ===== INTERNSHIP TITLE TEMPLATES =====
const TITLE_TEMPLATES: Record<string, string[]> = {
  Marketing: ['Digital Marketing Intern', 'Brand Management Intern', 'Social Media Marketing Intern', 'Content Marketing Intern', 'SEO/SEM Intern', 'Performance Marketing Intern', 'Growth Marketing Intern', 'Marketing Analytics Intern', 'Email Marketing Intern', 'Influencer Marketing Intern'],
  Finance: ['Financial Analyst Intern', 'Investment Banking Intern', 'Corporate Finance Intern', 'Equity Research Intern', 'Financial Modeling Intern', 'Risk Management Intern', 'Audit Intern', 'Tax Advisory Intern', 'Treasury Intern', 'Wealth Management Intern'],
  Operations: ['Operations Intern', 'Supply Chain Intern', 'Business Operations Intern', 'Process Improvement Intern', 'Logistics Intern', 'Quality Assurance Intern', 'Procurement Intern', 'Warehouse Operations Intern'],
  'Human Resources': ['HR Intern', 'Talent Acquisition Intern', 'People Operations Intern', 'HR Analytics Intern', 'Employee Engagement Intern', 'Learning & Development Intern', 'Compensation & Benefits Intern'],
  Consulting: ['Management Consulting Intern', 'Strategy Consulting Intern', 'Business Analyst Intern', 'Data Analytics Consultant Intern', 'Operations Consulting Intern', 'Technology Consulting Intern'],
  'Product Management': ['Product Management Intern', 'Associate Product Manager Intern', 'Product Strategy Intern', 'Product Analytics Intern', 'Technical Product Manager Intern'],
  'Data Analytics': ['Data Analyst Intern', 'Business Intelligence Intern', 'Data Science Intern', 'Machine Learning Intern', 'Analytics Intern', 'Data Engineering Intern'],
  'Business Development': ['Business Development Intern', 'Partnerships Intern', 'Sales & BD Intern', 'Strategic Alliances Intern', 'Client Relations Intern'],
  Sales: ['Sales Intern', 'Inside Sales Intern', 'Enterprise Sales Intern', 'Sales Operations Intern', 'Account Management Intern'],
  'IT/Software': ['Software Engineer Intern', 'Frontend Developer Intern', 'Backend Developer Intern', 'Full Stack Intern', 'Mobile App Developer Intern', 'DevOps Intern', 'QA Engineer Intern', 'Cloud Engineering Intern'],
  Design: ['UI/UX Design Intern', 'Graphic Design Intern', 'Product Design Intern', 'Visual Design Intern', 'Interaction Design Intern'],
};

const CATEGORIES = Object.keys(TITLE_TEMPLATES);

const LOCATIONS = ['Mumbai', 'Delhi', 'Bangalore', 'Hyderabad', 'Chennai', 'Pune', 'Kolkata', 'Ahmedabad', 'Gurgaon', 'Noida', 'Jaipur', 'Lucknow', 'Work from Home'];
const LOCATION_TYPES: ('remote' | 'onsite' | 'hybrid')[] = ['remote', 'onsite', 'hybrid'];
const SOURCES: InternshipSource[] = ['internshala', 'linkedin', 'naukri', 'indeed', 'unstop', 'glassdoor', 'angellist', 'letsintern', 'iimjobs', 'freshersworld', 'hirect', 'cutshort', 'wellfound', 'foundit', 'shine', 'apna'];

const SKILLS_BY_CATEGORY: Record<string, string[]> = {
  Marketing: ['SEO', 'Google Analytics', 'Social Media Marketing', 'Content Writing', 'Email Marketing', 'Canva', 'Facebook Ads', 'Instagram Marketing'],
  Finance: ['Excel', 'Financial Modeling', 'Bloomberg', 'SQL', 'Tally', 'SAP', 'Valuation', 'Python'],
  Operations: ['Excel', 'SQL', 'Lean Six Sigma', 'SAP', 'Project Management', 'Data Analysis'],
  'Human Resources': ['Communication', 'Excel', 'HRIS', 'Recruitment', 'Employee Relations'],
  Consulting: ['PowerPoint', 'Excel', 'Market Research', 'Problem Solving', 'Data Analysis', 'SQL'],
  'Product Management': ['SQL', 'Figma', 'JIRA', 'A/B Testing', 'Data Analysis', 'User Research'],
  'Data Analytics': ['Python', 'SQL', 'Tableau', 'Power BI', 'R', 'Excel', 'Machine Learning'],
  'Business Development': ['Communication', 'Salesforce', 'CRM', 'Negotiation', 'Market Research'],
  Sales: ['Communication', 'CRM', 'Cold Calling', 'Salesforce', 'Negotiation'],
  'IT/Software': ['JavaScript', 'Python', 'React', 'Node.js', 'SQL', 'Git', 'Docker', 'AWS'],
  Design: ['Figma', 'Adobe Suite', 'Sketch', 'Prototyping', 'User Research', 'Wireframing'],
};

const PERKS = ['Certificate', 'Letter of Recommendation', 'Flexible Hours', 'Free Meals', 'Health Insurance', 'Work from Home', 'Mentorship', 'Job Offer', 'Training', 'Networking Events'];

// ===== GENERATE REALISTIC INTERNSHIP =====
function generateInternship(index: number): Internship {
  const company = ALL_COMPANIES[index % ALL_COMPANIES.length];
  const category = CATEGORIES[index % CATEGORIES.length];
  const titles = TITLE_TEMPLATES[category] || TITLE_TEMPLATES['Marketing'];
  const title = titles[index % titles.length];
  const source = SOURCES[index % SOURCES.length];
  const location = LOCATIONS[index % LOCATIONS.length];
  const locationType = LOCATION_TYPES[index % 3];
  const skills = (SKILLS_BY_CATEGORY[category] || SKILLS_BY_CATEGORY['Marketing']).slice(0, 3 + (index % 4));

  const stipendBase = [0, 5000, 8000, 10000, 12000, 15000, 18000, 20000, 25000, 30000, 35000, 40000, 50000, 60000, 75000];
  const stipend = stipendBase[index % stipendBase.length];
  const duration = [1, 1, 2, 2, 2, 3, 3, 3, 3][index % 9];

  const now = new Date();
  const postedDaysAgo = Math.floor(Math.random() * 25) + 1;
  const deadlineDaysFromNow = Math.floor(Math.random() * 30) + 3;
  const postedDate = new Date(now.getTime() - postedDaysAgo * 86400000).toISOString();
  const deadline = new Date(now.getTime() + deadlineDaysFromNow * 86400000).toISOString();

  const applicants = Math.floor(Math.random() * 800) + 10;
  const openings = [1, 2, 3, 5, 10, 15, 20][index % 7];
  const matchScore = Math.floor(Math.random() * 45) + 55;
  const ghostScore = Math.floor(Math.random() * 30);
  const successRate = Math.floor(Math.random() * 35) + 5;

  const id = uuid();
  const hash = generateHash(title, company.name, location);

  return {
    id,
    title,
    company: company.name,
    companyLogo: undefined,
    companySize: company.size,
    companyRating: Math.round(company.rating * 10) / 10,
    source,
    sourceUrl: `https://${source}.com/internship/${id.slice(0, 8)}`,
    stipend,
    stipendCurrency: '₹',
    stipendType: stipend === 0 ? 'unpaid' : 'monthly',
    duration,
    durationUnit: 'months',
    location,
    locationType,
    category,
    skills,
    description: `Join ${company.name} as a ${title}. Work with industry leaders in ${company.sector} to gain hands-on experience in ${category.toLowerCase()}. This is an excellent opportunity for MBA students to build practical skills and professional network.`,
    responsibilities: [
      `Assist in ${category.toLowerCase()} projects and daily operations`,
      `Conduct market research and competitive analysis`,
      `Prepare presentations and reports for senior management`,
      `Collaborate with cross-functional teams`,
      `Contribute to strategic initiatives and planning`,
    ],
    requirements: [
      `Currently pursuing MBA or equivalent degree`,
      `Strong analytical and communication skills`,
      `Proficiency in ${skills.slice(0, 2).join(' and ')}`,
      `Self-motivated with attention to detail`,
    ],
    perks: PERKS.slice(index % 3, (index % 3) + 3 + (index % 3)),
    openings,
    applicants,
    postedDate,
    deadline,
    startDate: new Date(now.getTime() + (deadlineDaysFromNow + 7) * 86400000).toISOString(),
    isExpired: false,
    isPremium: index % 7 === 0,
    isVerified: index % 3 !== 2,
    matchScore,
    ghostScore,
    successRate,
    avgResponseDays: Math.floor(Math.random() * 10) + 1,
    alreadyApplied: false,
    companyTier: company.tier as any,
    sector: company.sector,
    tags: [category, company.sector, locationType],
    lastUpdated: new Date().toISOString(),
    hash,
  };
}

// ===== GENERATE FULL DATABASE =====
let internshipDB: Internship[] = [];
const TOTAL_INTERNSHIPS = 2000;

function ensureDB() {
  if (internshipDB.length === 0) {
    const seen = new Set<string>();
    for (let i = 0; i < TOTAL_INTERNSHIPS; i++) {
      const item = generateInternship(i);
      if (!seen.has(item.hash)) {
        seen.add(item.hash);
        internshipDB.push(item);
      }
    }
  }
  return internshipDB;
}

// ===== API FUNCTIONS =====
export async function fetchInternships(
  page: number = 1,
  pageSize: number = ITEMS_PER_PAGE,
  filters: FilterState = {} as FilterState,
  sort: SortField = 'stipend_high'
): Promise<PaginatedResponse<Internship>> {
  // Simulate network delay
  await new Promise((r) => setTimeout(r, 300 + Math.random() * 400));

  const db = ensureDB();
  let results = [...db];

  // Apply filters
  if (filters && Object.keys(filters).length > 0) {
    results = applyFilters(results, filters);
  }

  // Deduplicate
  results = deduplicateInternships(results);

  // Sort
  results = applySorting(results, sort);

  const total = results.length;
  const start = (page - 1) * pageSize;
  const end = start + pageSize;
  const pageData = results.slice(start, end);

  return {
    success: true,
    data: pageData,
    meta: {
      total,
      page,
      pageSize,
      hasMore: end < total,
      filters,
      sort,
    },
    timestamp: new Date().toISOString(),
  };
}

export async function fetchInternshipById(id: string): Promise<APIResponse<Internship | null>> {
  await new Promise((r) => setTimeout(r, 200));
  const db = ensureDB();
  const item = db.find((i) => i.id === id) || null;
  return {
    success: !!item,
    data: item,
    timestamp: new Date().toISOString(),
  };
}

export async function fetchAnalytics(): Promise<APIResponse<AnalyticsData>> {
  await new Promise((r) => setTimeout(r, 500));
  const db = ensureDB();

  const sourceStats = SOURCES.map((source) => {
    const items = db.filter((i) => i.source === source);
    return {
      source,
      count: items.length,
      applied: Math.floor(items.length * 0.1),
      successRate: Math.floor(Math.random() * 30) + 10,
    };
  });

  const categoryStats = CATEGORIES.map((cat) => {
    const items = db.filter((i) => i.category === cat);
    const avgStipend = items.length > 0 ? items.reduce((s, i) => s + i.stipend, 0) / items.length : 0;
    return { category: cat, count: items.length, avgStipend: Math.round(avgStipend) };
  });

  return {
    success: true,
    data: {
      totalListings: db.length,
      totalApplied: 47,
      totalShortlisted: 12,
      totalRejected: 18,
      totalOffers: 3,
      successRate: 25.5,
      avgResponseTime: 4.2,
      topSources: sourceStats,
      topCategories: categoryStats,
      applicationTimeline: Array.from({ length: 14 }, (_, i) => ({
        date: new Date(Date.now() - (13 - i) * 86400000).toISOString().split('T')[0],
        applied: Math.floor(Math.random() * 8) + 1,
        shortlisted: Math.floor(Math.random() * 3),
        rejected: Math.floor(Math.random() * 2),
        offers: i === 10 ? 1 : 0,
      })),
      stipendDistribution: [
        { range: '₹0-5K', count: db.filter((i) => i.stipend <= 5000).length, min: 0, max: 5000 },
        { range: '₹5K-10K', count: db.filter((i) => i.stipend > 5000 && i.stipend <= 10000).length, min: 5000, max: 10000 },
        { range: '₹10K-20K', count: db.filter((i) => i.stipend > 10000 && i.stipend <= 20000).length, min: 10000, max: 20000 },
        { range: '₹20K-35K', count: db.filter((i) => i.stipend > 20000 && i.stipend <= 35000).length, min: 20000, max: 35000 },
        { range: '₹35K-50K', count: db.filter((i) => i.stipend > 35000 && i.stipend <= 50000).length, min: 35000, max: 50000 },
        { range: '₹50K+', count: db.filter((i) => i.stipend > 50000).length, min: 50000, max: 100000 },
      ],
      weeklyActivity: Array.from({ length: 8 }, (_, i) => ({
        week: `Week ${i + 1}`,
        applications: Math.floor(Math.random() * 15) + 5,
        responses: Math.floor(Math.random() * 8) + 1,
      })),
    },
    timestamp: new Date().toISOString(),
  };
}

export async function applyToInternship(id: string, _credentials: Record<string, string>): Promise<APIResponse<{ status: ApplicationStatus }>> {
  await new Promise((r) => setTimeout(r, 1000 + Math.random() * 2000));
  const success = Math.random() > 0.15;
  return {
    success,
    data: { status: success ? 'applied' : 'not_applied' },
    error: success ? undefined : 'Application submission failed. Please try again.',
    timestamp: new Date().toISOString(),
  };
}

export async function chatWithLLM(message: string, context?: { internshipIds?: string[] }): Promise<APIResponse<string>> {
  await new Promise((r) => setTimeout(r, 800 + Math.random() * 1200));

  const responses: Record<string, string> = {
    default: `I've analyzed your query. Based on the current internship listings, here are my insights:\n\n**Key Recommendations:**\n1. Focus on internships with match scores above 70% for better success rates\n2. Companies in the Technology and Consulting sectors currently have the most openings\n3. Remote internships offer flexibility but onsite roles at Tier-1 companies provide better networking\n\n**Pro Tips:**\n- Apply within the first 48 hours of posting for 3x higher response rate\n- Customize your application for each company's culture\n- Use the batch apply feature wisely — quality over quantity\n\nWould you like me to analyze specific internships or help with your application strategy?`,
  };

  let response = responses.default;

  if (message.toLowerCase().includes('compare')) {
    response = `**Comparison Analysis:**\n\nI've compared the selected internships across key metrics:\n\n| Factor | Weight | Notes |\n|--------|--------|-------|\n| Stipend | 30% | Higher stipend indicates company values intern contributions |\n| Brand Value | 25% | Tier-1 companies boost resume significantly |\n| Learning | 25% | Check responsibilities for skill-building |\n| Success Rate | 20% | Historical data shows acceptance likelihood |\n\n**Recommendation:** Prioritize Tier-1 companies for brand value, even if stipend is slightly lower. The long-term career ROI is significantly higher.`;
  } else if (message.toLowerCase().includes('cover letter') || message.toLowerCase().includes('application')) {
    response = `**Cover Letter Tips for MBA Internships:**\n\n1. **Opening Hook:** Reference a specific company initiative or recent news\n2. **Value Proposition:** Connect your MBA specialization to the role\n3. **Quantify Impact:** Use numbers from previous experience\n4. **Cultural Fit:** Show you've researched the company culture\n5. **Close Strong:** Express specific interest in the team/project\n\n**Template Structure:**\n- Para 1: Why this company (show research)\n- Para 2: What you bring (skills + experience)\n- Para 3: How you'll contribute (specific value)\n- Para 4: Call to action\n\nWant me to draft one for a specific internship?`;
  } else if (message.toLowerCase().includes('risk') || message.toLowerCase().includes('safe')) {
    response = `**Security & Risk Assessment:**\n\n🟢 **Low Risk Sources:** Internshala, Unstop, LetsIntern, FreshersWorld\n- Lenient rate limits, batch-friendly\n- Standard cooldown: 10-15 minutes\n\n🟡 **Medium Risk:** Naukri, Indeed, Foundit\n- Moderate rate limiting\n- May require OTP verification\n- Cooldown: 15-20 minutes\n\n🔴 **High Risk:** LinkedIn, Glassdoor, Company Direct\n- Active bot detection\n- Account suspension possible\n- Recommended: Manual apply only\n\n**Best Practices:**\n- Never exceed 5 applications per batch\n- Wait for cooldown to complete\n- Use different sources in rotation\n- Keep session intervals realistic`;
  }

  return {
    success: true,
    data: response,
    timestamp: new Date().toISOString(),
  };
}

// ===== SEARCH SUGGESTIONS =====
export async function fetchSearchSuggestions(query: string): Promise<string[]> {
  if (!query || query.length < 2) return [];
  const db = ensureDB();
  const q = query.toLowerCase();
  const suggestions = new Set<string>();

  for (const item of db) {
    if (suggestions.size >= 8) break;
    if (item.title.toLowerCase().includes(q)) suggestions.add(item.title);
    if (item.company.toLowerCase().includes(q)) suggestions.add(item.company);
    if (item.category.toLowerCase().includes(q)) suggestions.add(item.category);
  }

  return Array.from(suggestions).slice(0, 8);
}
