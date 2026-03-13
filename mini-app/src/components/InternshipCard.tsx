// ============================================================
// INTERNSHIP CARD — Ultra Premium Card Component
// ============================================================

import React, { memo, useCallback } from 'react';
import { motion } from 'framer-motion';
import {
  MapPin, Clock, Users, Star, Shield, CheckCircle2,
  TrendingUp, AlertTriangle, Check, Building2
} from 'lucide-react';
import { useAppStore } from '@/store/useAppStore';
import {
  formatStipend, formatDuration, formatRelativeDate, formatDeadline,
  formatNumber, getMatchScoreColor, hapticFeedback, hapticSelection,
} from '@/utils/helpers';
import { SOURCE_CONFIG, TIER_LABELS } from '@/utils/constants';
import { SourceIcon, TierIcon } from '@/components/SourceIcons';
import type { Internship } from '@/types';

interface Props {
  internship: Internship;
  index: number;
}

const InternshipCard = memo(function InternshipCard({ internship, index }: Props) {
  const { selectedIds, lockedSource, toggleSelect, setDetailOpen } = useAppStore();
  const isSelected = selectedIds.has(internship.id);
  const sourceConfig = SOURCE_CONFIG[internship.source];
  const tierConfig = TIER_LABELS[internship.companyTier];
  const deadline = formatDeadline(internship.deadline);

  const canSelect = !lockedSource || lockedSource === internship.source;

  const handleSelect = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
    if (!canSelect && !isSelected) return;
    toggleSelect(internship.id);
    hapticSelection();
  }, [canSelect, isSelected, internship.id]);

  const handleOpen = useCallback(() => {
    setDetailOpen(internship.id);
    hapticFeedback('light');
  }, [internship.id]);

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, delay: Math.min(index * 0.03, 0.3) }}
      className={`internship-card ${isSelected ? 'selected' : ''} ${internship.alreadyApplied ? 'opacity-60' : ''}`}
    >
      {/* Premium Badge */}
      {internship.isPremium && (
        <div className="absolute -top-1.5 right-4 premium-tag">
          Premium
        </div>
      )}

      <div className="p-4" onClick={handleOpen}>
        {/* Top Row: Source + Deadline + Select */}
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <span
              className="source-badge"
              style={{ backgroundColor: sourceConfig.color + '12', color: sourceConfig.color }}
            >
              <SourceIcon source={internship.source} size={12} />
              {sourceConfig.name}
            </span>
            {internship.isVerified && (
              <span className="flex items-center gap-0.5 text-[10px] text-emerald-600 font-medium">
                <Shield className="w-3 h-3" />
              </span>
            )}
          </div>

          <div className="flex items-center gap-2">
            {deadline.expired ? (
              <span className="text-[10px] font-semibold text-status-danger bg-status-danger/8 px-2 py-0.5 rounded-md">
                Expired
              </span>
            ) : deadline.urgent ? (
              <span className="text-[10px] font-semibold text-amber-600 bg-amber-50 px-2 py-0.5 rounded-md flex items-center gap-0.5">
                <AlertTriangle className="w-3 h-3" /> {deadline.text}
              </span>
            ) : (
              <span className="text-[10px] text-primary-400 font-medium">
                {deadline.text}
              </span>
            )}

            {/* Checkbox */}
            <button
              onClick={handleSelect}
              className={`w-5 h-5 rounded-md border-2 flex items-center justify-center transition-all duration-200 ${
                isSelected
                  ? 'border-primary-900 bg-primary-900'
                  : canSelect
                    ? 'border-primary-300 hover:border-primary-500'
                    : 'border-primary-200 opacity-40 cursor-not-allowed'
              }`}
            >
              {isSelected && <Check className="w-3 h-3 text-white" />}
            </button>
          </div>
        </div>

        {/* Company + Title */}
        <div className="mb-3">
          <div className="flex items-center gap-1.5 mb-1">
            <div className="w-6 h-6 bg-primary-50 rounded-lg flex items-center justify-center">
              <Building2 className="w-3.5 h-3.5 text-primary-400" />
            </div>
            <span className="text-xs font-semibold text-primary-500 line-clamp-1">
              {internship.company}
            </span>
            {internship.companyRating > 0 && (
              <span className="flex items-center gap-0.5 text-[10px] text-primary-400">
                <Star className="w-3 h-3 text-amber-400 fill-amber-400" />
                {internship.companyRating}
              </span>
            )}
            {tierConfig && (
              <span
                className="inline-flex items-center gap-0.5 text-[9px] font-bold px-1.5 py-0.5 rounded"
                style={{ color: tierConfig.color, backgroundColor: tierConfig.color + '10' }}
              >
                <TierIcon tier={internship.companyTier} size={10} className="opacity-80" />
                {tierConfig.label}
              </span>
            )}
          </div>
          <h3 className="text-[13px] font-bold text-primary-900 line-clamp-2 leading-snug tracking-tight">
            {internship.title}
          </h3>
        </div>

        {/* Key Details Row */}
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 mb-3">
          {/* Stipend */}
          <div className="flex items-center gap-1">
            <span className="text-sm font-bold text-stipend-high">
              {formatStipend(internship.stipend)}
            </span>
          </div>

          {/* Duration */}
          <div className="flex items-center gap-1 text-xs text-primary-500">
            <Clock className="w-3.5 h-3.5 text-primary-300" />
            <span className="font-medium">{formatDuration(internship.duration)}</span>
          </div>

          {/* Location */}
          <div className="flex items-center gap-1 text-xs text-primary-500">
            <MapPin className="w-3.5 h-3.5 text-primary-300" />
            <span className="font-medium">{internship.location}</span>
            <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded ${
              internship.locationType === 'remote' ? 'bg-emerald-50 text-emerald-600' :
              internship.locationType === 'hybrid' ? 'bg-blue-50 text-blue-600' :
              'bg-primary-50 text-primary-500'
            }`}>
              {internship.locationType.toUpperCase()}
            </span>
          </div>
        </div>

        {/* Skills */}
        {internship.skills.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mb-3">
            {internship.skills.slice(0, 4).map((skill) => (
              <span
                key={skill}
                className="text-[10px] font-medium px-2 py-0.5 bg-primary-50 text-primary-600 rounded-md"
              >
                {skill}
              </span>
            ))}
            {internship.skills.length > 4 && (
              <span className="text-[10px] font-medium text-primary-400">
                +{internship.skills.length - 4}
              </span>
            )}
          </div>
        )}

        {/* Bottom Stats Row */}
        <div className="flex items-center justify-between pt-2.5" style={{ borderTop: '1px solid rgba(0,0,0,0.04)' }}>
          <div className="flex items-center gap-3">
            {/* Match Score */}
            <div className="flex items-center gap-1">
              <div
                className="w-1.5 h-1.5 rounded-full"
                style={{ backgroundColor: getMatchScoreColor(internship.matchScore) }}
              />
              <span className="text-[10px] font-bold" style={{ color: getMatchScoreColor(internship.matchScore) }}>
                {internship.matchScore}%
              </span>
            </div>

            {/* Success Rate */}
            <div className="flex items-center gap-1">
              <TrendingUp className="w-3 h-3 text-primary-300" />
              <span className="text-[10px] font-medium text-primary-400">
                {internship.successRate}%
              </span>
            </div>

            {/* Applicants */}
            <div className="flex items-center gap-1">
              <Users className="w-3 h-3 text-primary-300" />
              <span className="text-[10px] font-medium text-primary-400">
                {formatNumber(internship.applicants)}
              </span>
            </div>
          </div>

          {/* Applied Status or Posted Date */}
          <div className="flex items-center gap-1.5">
            {internship.alreadyApplied ? (
              <span className="flex items-center gap-0.5 text-[10px] font-bold text-emerald-600 bg-emerald-50 px-2 py-0.5 rounded-md">
                <CheckCircle2 className="w-3 h-3" /> Applied
              </span>
            ) : (
              <span className="text-[10px] text-primary-400">
                {formatRelativeDate(internship.postedDate)}
              </span>
            )}
          </div>
        </div>

        {/* Openings + Ghost Score (if concerning) */}
        {(internship.openings > 1 || internship.ghostScore > 50) && (
          <div className="flex items-center gap-3 mt-2">
            {internship.openings > 1 && (
              <span className="text-[10px] font-medium text-blue-600 bg-blue-50 px-2 py-0.5 rounded-md">
                {internship.openings} openings
              </span>
            )}
            {internship.ghostScore > 50 && (
              <span className="text-[10px] font-medium text-amber-600 bg-amber-50 px-2 py-0.5 rounded-md flex items-center gap-0.5">
                <AlertTriangle className="w-3 h-3" /> Ghost risk: {internship.ghostScore}%
              </span>
            )}
          </div>
        )}
      </div>
    </motion.div>
  );
});

export default InternshipCard;
