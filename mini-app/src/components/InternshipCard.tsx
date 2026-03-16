// ============================================================
// INTERNSHIP CARD — PRISM v0.1 Ultra Premium Card
// Smooth entrance, depth hover, micro-interactions
// ============================================================

import React, { memo, useCallback } from 'react';
import { motion } from 'framer-motion';
import {
  MapPin, Clock, Users, Star, Shield, CheckCircle2,
  TrendingUp, AlertTriangle, Check, Building2, Sparkles
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
  const sourceConfig = SOURCE_CONFIG[internship.source] || { name: internship.source || 'Unknown', color: '#6b7280', icon: 'company_direct', maxBatchSize: 3, cooldownMinutes: 15, riskLevel: 'medium' as const };
  const tierConfig = TIER_LABELS[internship.companyTier];
  const deadline = formatDeadline(internship.deadline);

  const canSelect = !lockedSource || lockedSource === internship.source;

  const isBlueOcean = internship.matchScore >= 80 && internship.applicants < 50;
  const isHighPay = internship.stipend >= 25000;

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
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{
        duration: 0.4,
        delay: Math.min(index * 0.04, 0.3),
        ease: [0.22, 1, 0.36, 1],
      }}
      className={`internship-card ${isSelected ? 'selected' : ''} ${internship.alreadyApplied ? 'opacity-55' : ''}`}
      style={{
        willChange: 'transform',
      }}
    >
      {/* Blue Ocean Badge */}
      {isBlueOcean && !internship.isPremium && (
        <div
          className="absolute -top-1.5 right-4 text-[9px] font-bold px-2.5 py-0.5 uppercase tracking-wider rounded-b-md flex items-center gap-1"
          style={{
            background: 'linear-gradient(135deg, #059669, #10b981)',
            color: '#ffffff',
            boxShadow: '0 2px 8px rgba(5,150,105,0.3)',
          }}
        >
          <Sparkles className="w-2.5 h-2.5" />
          Blue Ocean
        </div>
      )}

      {/* Premium Badge */}
      {internship.isPremium && (
        <div className="absolute -top-1.5 right-4 premium-tag">
          Premium
        </div>
      )}

      <div className="p-4 cursor-pointer active:bg-gray-50 transition-colors" onClick={handleOpen} role="button" tabIndex={0} onKeyDown={(e) => { if (e.key === 'Enter') handleOpen(); }}>
        {/* Top Row: Source + Deadline + Select */}
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <motion.span
              className="source-badge"
              style={{ backgroundColor: sourceConfig.color + '10', color: sourceConfig.color }}
              whileTap={{ scale: 0.95 }}
            >
              <SourceIcon source={internship.source} size={12} />
              {sourceConfig.name}
            </motion.span>
            {internship.isVerified && (
              <span className="flex items-center gap-0.5 text-[10px] text-emerald-600 font-medium">
                <Shield className="w-3 h-3" />
              </span>
            )}
          </div>

          <div className="flex items-center gap-2">
            {deadline.expired ? (
              <span className="text-[10px] font-semibold px-2 py-0.5 rounded-md"
                style={{ background: '#fef2f2', color: '#dc2626' }}>
                Expired
              </span>
            ) : deadline.urgent ? (
              <span className="text-[10px] font-semibold px-2 py-0.5 rounded-md flex items-center gap-0.5"
                style={{ background: '#fffbeb', color: '#d97706' }}>
                <AlertTriangle className="w-3 h-3" /> {deadline.text}
              </span>
            ) : (
              <span className="text-[10px] text-primary-400 font-medium">
                {deadline.text}
              </span>
            )}

            {/* Checkbox — animated, sized for touch */}
            <motion.button
              onClick={handleSelect}
              className={`flex-shrink-0 rounded-lg border-2 flex items-center justify-center transition-colors duration-200 ${
                isSelected
                  ? 'border-[#0a0a0a] bg-[#0a0a0a]'
                  : canSelect
                    ? 'border-[#9ca3af] hover:border-[#6b7280] bg-white'
                    : 'border-[#d1d5db] bg-[#f9fafb] opacity-50 cursor-not-allowed'
              }`}
              style={{ width: '26px', height: '26px', minWidth: '26px' }}
              whileTap={canSelect ? { scale: 0.85 } : {}}
            >
              {isSelected ? (
                <motion.div
                  initial={{ scale: 0 }}
                  animate={{ scale: 1 }}
                  transition={{ type: 'spring', stiffness: 500, damping: 15 }}
                >
                  <Check className="w-3.5 h-3.5 text-white" />
                </motion.div>
              ) : canSelect ? (
                <div className="w-2.5 h-2.5 rounded-sm border border-[#d1d5db]" />
              ) : null}
            </motion.button>
          </div>
        </div>

        {/* Company + Title */}
        <div className="mb-3">
          <div className="flex items-center gap-1.5 mb-1">
            <div
              className="w-7 h-7 rounded-lg flex items-center justify-center"
              style={{ background: '#f8f9fa', border: '1px solid rgba(229,231,235,0.6)' }}
            >
              <Building2 className="w-3.5 h-3.5 text-primary-400" />
            </div>
            <span className="text-xs font-semibold text-primary-500 line-clamp-1 flex-1">
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
            <span
              className="text-sm font-bold"
              style={{
                color: isHighPay ? '#059669' : '#0a0a0a',
              }}
            >
              {formatStipend(internship.stipend)}
            </span>
            {isHighPay && (
              <span className="text-[8px] font-bold px-1 py-0.5 rounded bg-emerald-50 text-emerald-600">
                TOP
              </span>
            )}
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
                className="text-[10px] font-medium px-2 py-0.5 rounded-md transition-colors"
                style={{ background: '#f3f4f6', color: '#4b5563', border: '1px solid rgba(229,231,235,0.5)' }}
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
        <div className="flex items-center justify-between pt-2.5" style={{ borderTop: '1px solid rgba(229,231,235,0.5)' }}>
          <div className="flex items-center gap-3">
            {/* Match Score — with color-coded ring */}
            <div className="flex items-center gap-1.5">
              <div
                className="w-6 h-6 rounded-full flex items-center justify-center text-[9px] font-bold"
                style={{
                  background: getMatchScoreColor(internship.matchScore) + '12',
                  color: getMatchScoreColor(internship.matchScore),
                  border: `1.5px solid ${getMatchScoreColor(internship.matchScore)}30`,
                }}
              >
                {internship.matchScore}
              </div>
              <span className="text-[10px] font-medium text-primary-400">Match</span>
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

        {/* Openings + Ghost Score */}
        {(internship.openings > 1 || internship.ghostScore > 50) && (
          <div className="flex items-center gap-2 mt-2">
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
