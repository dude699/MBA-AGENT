// ============================================================
// INTERNSHIP DETAIL — Full Detail Sheet
// ============================================================

import React from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  X, ExternalLink, MapPin, Clock, Users, Star, Shield, Building2,
  DollarSign, Calendar, TrendingUp, Briefcase, CheckCircle2,
  AlertTriangle, ChevronRight, Gift, BookOpen, Target, Share2
} from 'lucide-react';
import { useAppStore } from '@/store/useAppStore';
import {
  formatStipend, formatDuration, formatDate, formatRelativeDate,
  formatDeadline, formatNumber, getMatchScoreColor, hapticFeedback,
} from '@/utils/helpers';
import { SOURCE_CONFIG, TIER_LABELS } from '@/utils/constants';
import type { Internship } from '@/types';

export default function InternshipDetail() {
  const { isDetailOpen, setDetailOpen, internships, toggleSelect, selectedIds } = useAppStore();

  if (!isDetailOpen) return null;

  const item = internships.find((i) => i.id === isDetailOpen);
  if (!item) return null;

  const sourceConfig = SOURCE_CONFIG[item.source];
  const tierConfig = TIER_LABELS[item.companyTier];
  const deadline = formatDeadline(item.deadline);
  const isSelected = selectedIds.has(item.id);

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 z-50 bg-black/40 backdrop-blur-sm"
        onClick={() => setDetailOpen(null)}
      >
        <motion.div
          initial={{ y: '100%' }}
          animate={{ y: 0 }}
          exit={{ y: '100%' }}
          transition={{ type: 'spring', damping: 30, stiffness: 300 }}
          className="absolute bottom-0 left-0 right-0 bg-white rounded-t-3xl h-[92vh] flex flex-col"
          onClick={(e) => e.stopPropagation()}
        >
          {/* Handle */}
          <div className="flex justify-center pt-3 pb-1">
            <div className="w-10 h-1 bg-primary-200 rounded-full" />
          </div>

          {/* Header */}
          <div className="flex items-center justify-between px-5 py-2 border-b border-surface-border">
            <span className="text-xs font-semibold text-primary-500">Internship Details</span>
            <div className="flex items-center gap-2">
              <button
                onClick={() => window.open(item.sourceUrl, '_blank')}
                className="p-1.5 rounded-lg hover:bg-surface-muted transition-colors"
              >
                <ExternalLink className="w-4 h-4 text-primary-500" />
              </button>
              <button onClick={() => setDetailOpen(null)} className="p-1.5">
                <X className="w-5 h-5 text-primary-500" />
              </button>
            </div>
          </div>

          {/* Content */}
          <div className="flex-1 overflow-y-auto pb-24">
            {/* Hero Section */}
            <div className="px-5 pt-4 pb-3">
              {/* Source & Status */}
              <div className="flex items-center gap-2 mb-3">
                <span
                  className="text-[10px] font-bold px-2.5 py-0.5 rounded-md"
                  style={{ backgroundColor: sourceConfig.color + '15', color: sourceConfig.color }}
                >
                  {sourceConfig.icon} {sourceConfig.name}
                </span>
                {item.isVerified && (
                  <span className="badge-status"><Shield className="w-3 h-3 mr-0.5" /> Verified</span>
                )}
                {item.isPremium && (
                  <span className="badge bg-amber-100 text-amber-700">Premium</span>
                )}
                {item.alreadyApplied && (
                  <span className="badge-status"><CheckCircle2 className="w-3 h-3 mr-0.5" /> Applied</span>
                )}
              </div>

              {/* Company */}
              <div className="flex items-center gap-2 mb-2">
                <div className="w-10 h-10 bg-surface-muted rounded-xl flex items-center justify-center border border-surface-border">
                  <Building2 className="w-5 h-5 text-primary-400" />
                </div>
                <div>
                  <p className="text-sm font-bold text-primary-800">{item.company}</p>
                  <div className="flex items-center gap-2 text-[10px] text-primary-500">
                    {item.companyRating && (
                      <span className="flex items-center gap-0.5">
                        <Star className="w-3 h-3 text-amber-400 fill-amber-400" /> {item.companyRating}
                      </span>
                    )}
                    {tierConfig && (
                      <span style={{ color: tierConfig.color }}>{tierConfig.icon} {tierConfig.label}</span>
                    )}
                    {item.companySize && <span>{item.companySize} employees</span>}
                  </div>
                </div>
              </div>

              {/* Title */}
              <h2 className="text-lg font-bold text-primary-950 leading-snug mb-3">
                {item.title}
              </h2>

              {/* Key Stats Grid */}
              <div className="grid grid-cols-2 gap-2 mb-4">
                <StatBox
                  icon={<DollarSign className="w-4 h-4 text-stipend-high" />}
                  label="Stipend"
                  value={formatStipend(item.stipend)}
                  valueColor="text-stipend-high"
                />
                <StatBox
                  icon={<Clock className="w-4 h-4 text-status-info" />}
                  label="Duration"
                  value={formatDuration(item.duration)}
                  valueColor="text-status-info"
                />
                <StatBox
                  icon={<MapPin className="w-4 h-4 text-primary-500" />}
                  label="Location"
                  value={`${item.location} (${item.locationType})`}
                />
                <StatBox
                  icon={<Calendar className="w-4 h-4 text-primary-500" />}
                  label="Deadline"
                  value={deadline.text}
                  valueColor={deadline.urgent ? 'text-status-danger' : undefined}
                />
              </div>

              {/* Match & Performance Row */}
              <div className="flex gap-3 mb-4">
                <div className="flex-1 stat-card">
                  <div className="flex items-center justify-center gap-1 mb-1">
                    <div className="w-3 h-3 rounded-full" style={{ backgroundColor: getMatchScoreColor(item.matchScore) }} />
                    <span className="text-lg font-bold" style={{ color: getMatchScoreColor(item.matchScore) }}>{item.matchScore}%</span>
                  </div>
                  <p className="text-[10px] text-primary-500 font-medium">Match Score</p>
                </div>
                <div className="flex-1 stat-card">
                  <p className="text-lg font-bold text-status-success">{item.successRate}%</p>
                  <p className="text-[10px] text-primary-500 font-medium">Success Rate</p>
                </div>
                <div className="flex-1 stat-card">
                  <p className="text-lg font-bold text-primary-700">{item.avgResponseDays}d</p>
                  <p className="text-[10px] text-primary-500 font-medium">Avg Response</p>
                </div>
              </div>

              <div className="flex items-center justify-between px-1 mb-3">
                <div className="flex items-center gap-1 text-xs text-primary-500">
                  <Users className="w-3.5 h-3.5" />
                  <span>{formatNumber(item.applicants)} applicants</span>
                </div>
                <div className="flex items-center gap-1 text-xs text-primary-500">
                  <Briefcase className="w-3.5 h-3.5" />
                  <span>{item.openings} openings</span>
                </div>
                <span className="text-xs text-primary-400">Posted {formatRelativeDate(item.postedDate)}</span>
              </div>
            </div>

            <div className="h-px bg-surface-border" />

            {/* Description */}
            <Section title="About This Role" icon={<BookOpen className="w-4 h-4" />}>
              <p className="text-xs text-primary-700 leading-relaxed">{item.description}</p>
            </Section>

            {/* Skills */}
            <Section title="Required Skills" icon={<Target className="w-4 h-4" />}>
              <div className="flex flex-wrap gap-1.5">
                {item.skills.map((skill) => (
                  <span key={skill} className="text-[11px] font-medium px-2.5 py-1 bg-surface-muted text-primary-700 rounded-lg border border-surface-border">
                    {skill}
                  </span>
                ))}
              </div>
            </Section>

            {/* Responsibilities */}
            <Section title="Responsibilities" icon={<Briefcase className="w-4 h-4" />}>
              <ul className="space-y-1.5">
                {item.responsibilities.map((resp, idx) => (
                  <li key={idx} className="flex items-start gap-2 text-xs text-primary-700">
                    <span className="w-1.5 h-1.5 rounded-full bg-accent mt-1.5 flex-shrink-0" />
                    {resp}
                  </li>
                ))}
              </ul>
            </Section>

            {/* Requirements */}
            <Section title="Requirements" icon={<CheckCircle2 className="w-4 h-4" />}>
              <ul className="space-y-1.5">
                {item.requirements.map((req, idx) => (
                  <li key={idx} className="flex items-start gap-2 text-xs text-primary-700">
                    <CheckCircle2 className="w-3.5 h-3.5 text-status-success flex-shrink-0 mt-0.5" />
                    {req}
                  </li>
                ))}
              </ul>
            </Section>

            {/* Perks */}
            {item.perks.length > 0 && (
              <Section title="Perks" icon={<Gift className="w-4 h-4" />}>
                <div className="flex flex-wrap gap-1.5">
                  {item.perks.map((perk) => (
                    <span key={perk} className="text-[11px] font-medium px-2.5 py-1 bg-emerald-50 text-emerald-700 rounded-lg border border-emerald-100">
                      {perk}
                    </span>
                  ))}
                </div>
              </Section>
            )}

            {/* Ghost Score Warning */}
            {item.ghostScore > 40 && (
              <div className="mx-5 mb-4 p-3 bg-status-warning/5 border border-status-warning/20 rounded-xl">
                <div className="flex items-center gap-2 mb-1">
                  <AlertTriangle className="w-4 h-4 text-status-warning" />
                  <span className="text-xs font-bold text-status-warning">Ghost Posting Risk: {item.ghostScore}%</span>
                </div>
                <p className="text-[11px] text-primary-600">
                  This listing has indicators of being a ghost posting. Consider verifying with the company directly before applying.
                </p>
              </div>
            )}
          </div>

          {/* Bottom Action Bar */}
          <div className="absolute bottom-0 left-0 right-0 p-4 bg-white/95 backdrop-blur-md border-t border-surface-border flex gap-3">
            <button
              onClick={() => { toggleSelect(item.id); hapticFeedback('medium'); }}
              className={`flex-1 py-3 rounded-xl font-semibold text-sm transition-all ${
                isSelected
                  ? 'bg-accent/10 text-accent border-2 border-accent'
                  : 'bg-accent text-white'
              }`}
            >
              {isSelected ? 'Deselect' : 'Select for Auto-Apply'}
            </button>
            <button
              onClick={() => window.open(item.sourceUrl, '_blank')}
              className="py-3 px-5 bg-surface-muted border border-surface-border rounded-xl text-sm font-semibold text-primary-700 flex items-center gap-1.5"
            >
              <ExternalLink className="w-4 h-4" /> Apply
            </button>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}

// ===== STAT BOX =====
function StatBox({
  icon, label, value, valueColor,
}: {
  icon: React.ReactNode; label: string; value: string; valueColor?: string;
}) {
  return (
    <div className="flex items-center gap-2.5 p-2.5 bg-surface-muted rounded-xl border border-surface-border">
      {icon}
      <div>
        <p className="text-[10px] text-primary-500 font-medium">{label}</p>
        <p className={`text-xs font-bold ${valueColor || 'text-primary-800'}`}>{value}</p>
      </div>
    </div>
  );
}

// ===== SECTION =====
function Section({
  title, icon, children,
}: {
  title: string; icon: React.ReactNode; children: React.ReactNode;
}) {
  return (
    <div className="px-5 py-4 border-b border-surface-border">
      <div className="flex items-center gap-2 mb-3">
        <span className="text-primary-500">{icon}</span>
        <h3 className="text-sm font-bold text-primary-800">{title}</h3>
      </div>
      {children}
    </div>
  );
}
