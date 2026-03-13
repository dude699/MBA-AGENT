// ============================================================
// SOURCE ICONS — Professional SVG Icons for All Platforms
// ============================================================
// Replaces all emoji icons with clean, professional SVG icons
// ============================================================

import React from 'react';

interface IconProps {
  className?: string;
  size?: number;
}

// ===== INTERNSHALA =====
export function InternshalaIcon({ className = '', size = 16 }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} className={className} fill="none">
      <rect x="2" y="3" width="20" height="18" rx="3" stroke="currentColor" strokeWidth="1.8" />
      <path d="M7 8h10M7 12h7M7 16h4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      <circle cx="18" cy="14" r="2.5" fill="currentColor" opacity="0.3" />
    </svg>
  );
}

// ===== LINKEDIN =====
export function LinkedInIcon({ className = '', size = 16 }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} className={className}>
      <path
        d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433a2.062 2.062 0 01-2.063-2.065 2.064 2.064 0 112.063 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z"
        fill="currentColor"
      />
    </svg>
  );
}

// ===== NAUKRI =====
export function NaukriIcon({ className = '', size = 16 }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} className={className} fill="none">
      <rect x="2" y="6" width="20" height="14" rx="2" stroke="currentColor" strokeWidth="1.8" />
      <path d="M8 6V4a2 2 0 012-2h4a2 2 0 012 2v2" stroke="currentColor" strokeWidth="1.8" />
      <path d="M2 11h20" stroke="currentColor" strokeWidth="1.8" />
      <circle cx="12" cy="11" r="2" fill="currentColor" />
    </svg>
  );
}

// ===== INDEED =====
export function IndeedIcon({ className = '', size = 16 }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} className={className} fill="none">
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="1.8" />
      <path d="M12 7v5l3 3" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="12" cy="6" r="1" fill="currentColor" />
    </svg>
  );
}

// ===== GLASSDOOR =====
export function GlassdoorIcon({ className = '', size = 16 }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} className={className} fill="none">
      <rect x="3" y="2" width="18" height="20" rx="2" stroke="currentColor" strokeWidth="1.8" />
      <path d="M3 8h18" stroke="currentColor" strokeWidth="1.8" />
      <rect x="7" y="11" width="4" height="4" rx="0.5" fill="currentColor" opacity="0.4" />
      <rect x="13" y="11" width="4" height="4" rx="0.5" fill="currentColor" opacity="0.4" />
      <rect x="7" y="17" width="4" height="2" rx="0.5" fill="currentColor" opacity="0.2" />
      <rect x="13" y="17" width="4" height="2" rx="0.5" fill="currentColor" opacity="0.2" />
    </svg>
  );
}

// ===== ANGELLIST =====
export function AngelListIcon({ className = '', size = 16 }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} className={className} fill="none">
      <path d="M12 2L15 9h7l-5.5 4.5L18.5 22 12 17.5 5.5 22l2-8.5L2 9h7L12 2z" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
    </svg>
  );
}

// ===== UNSTOP =====
export function UnstopIcon({ className = '', size = 16 }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} className={className} fill="none">
      <path d="M12 2L4 7v10l8 5 8-5V7l-8-5z" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
      <path d="M12 8v5l4 2.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

// ===== LETSINTERN =====
export function LetsInternIcon({ className = '', size = 16 }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} className={className} fill="none">
      <path d="M22 10L12 2 2 10" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M12 2v6" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      <rect x="4" y="10" width="16" height="2" rx="1" fill="currentColor" />
      <path d="M6 14v5a2 2 0 002 2h8a2 2 0 002-2v-5" stroke="currentColor" strokeWidth="1.8" />
      <path d="M10 17h4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}

// ===== IIMJOBS =====
export function IIMJobsIcon({ className = '', size = 16 }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} className={className} fill="none">
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="1.8" />
      <path d="M12 6v6l4 4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M8 2.5l4 1.5 4-1.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

// ===== FRESHERSWORLD =====
export function FreshersWorldIcon({ className = '', size = 16 }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} className={className} fill="none">
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="1.8" />
      <path d="M8 14s1.5 2 4 2 4-2 4-2" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      <path d="M9 9h.01M15 9h.01" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
      <path d="M2 12h2M20 12h2M12 2v2M12 20v2" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" opacity="0.4" />
    </svg>
  );
}

// ===== HIRECT =====
export function HirectIcon({ className = '', size = 16 }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} className={className} fill="none">
      <rect x="5" y="2" width="14" height="20" rx="3" stroke="currentColor" strokeWidth="1.8" />
      <path d="M9 18h6" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      <circle cx="12" cy="10" r="3" stroke="currentColor" strokeWidth="1.5" />
      <path d="M9 5h6" stroke="currentColor" strokeWidth="1" strokeLinecap="round" opacity="0.4" />
    </svg>
  );
}

// ===== CUTSHORT =====
export function CutShortIcon({ className = '', size = 16 }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} className={className} fill="none">
      <circle cx="7" cy="17" r="3" stroke="currentColor" strokeWidth="1.8" />
      <circle cx="17" cy="17" r="3" stroke="currentColor" strokeWidth="1.8" />
      <path d="M7 14L17 4M17 14L7 4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}

// ===== WELLFOUND =====
export function WellfoundIcon({ className = '', size = 16 }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} className={className} fill="none">
      <path d="M4 12l4 8 4-12 4 12 4-8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="12" cy="4" r="2" fill="currentColor" opacity="0.3" />
    </svg>
  );
}

// ===== FOUNDIT =====
export function FounditIcon({ className = '', size = 16 }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} className={className} fill="none">
      <circle cx="10.5" cy="10.5" r="7" stroke="currentColor" strokeWidth="1.8" />
      <path d="M16 16l5 5" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
      <path d="M8 10.5h5M10.5 8v5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

// ===== SHINE =====
export function ShineIcon({ className = '', size = 16 }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} className={className} fill="none">
      <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      <circle cx="12" cy="12" r="3" fill="currentColor" opacity="0.3" stroke="currentColor" strokeWidth="1.5" />
    </svg>
  );
}

// ===== APNA =====
export function ApnaIcon({ className = '', size = 16 }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} className={className} fill="none">
      <rect x="3" y="4" width="18" height="16" rx="3" stroke="currentColor" strokeWidth="1.8" />
      <circle cx="12" cy="11" r="3" stroke="currentColor" strokeWidth="1.5" />
      <path d="M7 18c0-2.5 2.2-4 5-4s5 1.5 5 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

// ===== COMPANY DIRECT =====
export function CompanyDirectIcon({ className = '', size = 16 }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} className={className} fill="none">
      <rect x="3" y="8" width="18" height="14" rx="1" stroke="currentColor" strokeWidth="1.8" />
      <path d="M3 8l9-6 9 6" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
      <rect x="7" y="12" width="3" height="4" rx="0.5" fill="currentColor" opacity="0.3" />
      <rect x="14" y="12" width="3" height="4" rx="0.5" fill="currentColor" opacity="0.3" />
      <rect x="10" y="16" width="4" height="6" rx="0.5" fill="currentColor" opacity="0.2" />
    </svg>
  );
}

// ===== TIER ICONS =====
export function CrownIcon({ className = '', size = 16 }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} className={className} fill="none">
      <path d="M2 18L5 8l4 4 3-8 3 8 4-4 3 10H2z" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
      <path d="M4 20h16" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}

export function DiamondIcon({ className = '', size = 16 }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} className={className} fill="none">
      <path d="M5 4h14l3 6-10 12L2 10l3-6z" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
      <path d="M2 10h20" stroke="currentColor" strokeWidth="1.2" opacity="0.5" />
    </svg>
  );
}

export function StarFilledIcon({ className = '', size = 16 }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} className={className}>
      <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" fill="currentColor" />
    </svg>
  );
}

export function RocketIcon({ className = '', size = 16 }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} className={className} fill="none">
      <path d="M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 00-2.91-.09z" stroke="currentColor" strokeWidth="1.5" />
      <path d="M12 15l-3-3a22 22 0 012-3.95A12.88 12.88 0 0122 2c0 2.72-.78 7.5-6 11.95A22 22 0 0112 15z" stroke="currentColor" strokeWidth="1.8" />
      <path d="M9 12H4s.55-3.03 2-4c1.62-1.08 5 0 5 0M12 15v5s3.03-.55 4-2c1.08-1.62 0-5 0-5" stroke="currentColor" strokeWidth="1.5" />
    </svg>
  );
}

export function GlobeIcon({ className = '', size = 16 }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} className={className} fill="none">
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="1.8" />
      <path d="M2 12h20M12 2a15.3 15.3 0 014 10 15.3 15.3 0 01-4 10 15.3 15.3 0 01-4-10 15.3 15.3 0 014-10z" stroke="currentColor" strokeWidth="1.5" />
    </svg>
  );
}

export function LandmarkIcon({ className = '', size = 16 }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} className={className} fill="none">
      <path d="M3 21h18M5 21V10M19 21V10M9 21V10M15 21V10M3 10l9-7 9 7" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function HeartIcon({ className = '', size = 16 }: IconProps) {
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} className={className} fill="none">
      <path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0016.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 002 8.5c0 2.3 1.5 4.05 3 5.5l7 7 7-7z" stroke="currentColor" strokeWidth="1.8" />
    </svg>
  );
}

// ===== SOURCE ICON MAPPER =====
export const SOURCE_ICON_MAP: Record<string, React.FC<IconProps>> = {
  internshala: InternshalaIcon,
  linkedin: LinkedInIcon,
  naukri: NaukriIcon,
  indeed: IndeedIcon,
  glassdoor: GlassdoorIcon,
  angellist: AngelListIcon,
  unstop: UnstopIcon,
  letsintern: LetsInternIcon,
  iimjobs: IIMJobsIcon,
  freshersworld: FreshersWorldIcon,
  hirect: HirectIcon,
  cutshort: CutShortIcon,
  wellfound: WellfoundIcon,
  foundit: FounditIcon,
  shine: ShineIcon,
  apna: ApnaIcon,
  company_direct: CompanyDirectIcon,
};

export const TIER_ICON_MAP: Record<string, React.FC<IconProps>> = {
  tier1: CrownIcon,
  tier2: DiamondIcon,
  tier3: StarFilledIcon,
  startup: RocketIcon,
  mnc: GlobeIcon,
  govt: LandmarkIcon,
  ngo: HeartIcon,
};

// ===== HELPER: Get Source Icon Component =====
export function SourceIcon({ source, className = '', size = 14 }: { source: string; className?: string; size?: number }) {
  const IconComponent = SOURCE_ICON_MAP[source];
  if (!IconComponent) return null;
  return <IconComponent className={className} size={size} />;
}

export function TierIcon({ tier, className = '', size = 14 }: { tier: string; className?: string; size?: number }) {
  const IconComponent = TIER_ICON_MAP[tier];
  if (!IconComponent) return null;
  return <IconComponent className={className} size={size} />;
}
