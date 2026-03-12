// ============================================================
// ANALYTICS DASHBOARD — Stats & Insights
// ============================================================

import React from 'react';
import { motion } from 'framer-motion';
import {
  BarChart3, TrendingUp, Target, Users, Briefcase, CheckCircle2,
  XCircle, Send, Clock, ChevronLeft, Award
} from 'lucide-react';
import { useAnalytics } from '@/hooks/useHooks';
import { SOURCE_CONFIG } from '@/utils/constants';
import { formatNumber } from '@/utils/helpers';

export default function AnalyticsDashboard() {
  const { data: response, isLoading } = useAnalytics();
  const analytics = response?.data;

  if (isLoading || !analytics) {
    return (
      <div className="px-5 py-8">
        <div className="space-y-4">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="skeleton h-20 rounded-2xl" />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="px-5 py-4 space-y-4" id="analytics">
      {/* Header */}
      <div className="flex items-center gap-2 mb-2">
        <BarChart3 className="w-5 h-5 text-accent" />
        <h2 className="text-base font-bold text-primary-900">Analytics Dashboard</h2>
      </div>

      {/* Key Metrics */}
      <div className="grid grid-cols-2 gap-3">
        <MetricCard
          icon={<Briefcase className="w-5 h-5 text-status-info" />}
          label="Total Listings"
          value={formatNumber(analytics.totalListings)}
          color="bg-status-info/10"
        />
        <MetricCard
          icon={<Send className="w-5 h-5 text-accent" />}
          label="Applied"
          value={analytics.totalApplied.toString()}
          color="bg-accent/10"
        />
        <MetricCard
          icon={<CheckCircle2 className="w-5 h-5 text-status-success" />}
          label="Shortlisted"
          value={analytics.totalShortlisted.toString()}
          color="bg-status-success/10"
        />
        <MetricCard
          icon={<Award className="w-5 h-5 text-amber-500" />}
          label="Offers"
          value={analytics.totalOffers.toString()}
          color="bg-amber-50"
        />
      </div>

      {/* Success Rate */}
      <div className="bg-gradient-to-r from-accent to-accent-light rounded-2xl p-4 text-white">
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs font-medium text-white/80">Overall Success Rate</span>
          <TrendingUp className="w-4 h-4 text-white/60" />
        </div>
        <p className="text-3xl font-bold">{analytics.successRate}%</p>
        <div className="w-full h-2 bg-white/20 rounded-full mt-2">
          <div
            className="h-full bg-white rounded-full transition-all duration-500"
            style={{ width: `${Math.min(analytics.successRate, 100)}%` }}
          />
        </div>
        <div className="flex justify-between mt-2 text-[10px] text-white/70">
          <span>Avg Response: {analytics.avgResponseTime} days</span>
          <span>{analytics.totalRejected} rejected</span>
        </div>
      </div>

      {/* Top Sources */}
      <div>
        <p className="section-header">Top Sources by Listings</p>
        <div className="space-y-2">
          {analytics.topSources
            .sort((a, b) => b.count - a.count)
            .slice(0, 8)
            .map((stat) => {
              const config = SOURCE_CONFIG[stat.source];
              if (!config) return null;
              const maxCount = analytics.topSources[0]?.count || 1;
              return (
                <div key={stat.source} className="flex items-center gap-3">
                  <span className="text-sm w-6 text-center">{config.icon}</span>
                  <div className="flex-1">
                    <div className="flex items-center justify-between mb-0.5">
                      <span className="text-xs font-medium text-primary-700">{config.name}</span>
                      <span className="text-xs font-bold text-primary-800">{stat.count}</span>
                    </div>
                    <div className="w-full h-1.5 bg-surface-muted rounded-full overflow-hidden">
                      <motion.div
                        className="h-full rounded-full"
                        style={{ backgroundColor: config.color }}
                        initial={{ width: 0 }}
                        animate={{ width: `${(stat.count / maxCount) * 100}%` }}
                        transition={{ duration: 0.6, delay: 0.1 }}
                      />
                    </div>
                  </div>
                </div>
              );
            })}
        </div>
      </div>

      {/* Top Categories */}
      <div>
        <p className="section-header">Top Categories</p>
        <div className="space-y-2">
          {analytics.topCategories
            .sort((a, b) => b.count - a.count)
            .slice(0, 8)
            .map((stat) => {
              const maxCount = analytics.topCategories[0]?.count || 1;
              return (
                <div key={stat.category} className="flex items-center gap-3">
                  <div className="flex-1">
                    <div className="flex items-center justify-between mb-0.5">
                      <span className="text-xs font-medium text-primary-700">{stat.category}</span>
                      <div className="flex items-center gap-2">
                        <span className="text-[10px] text-primary-400">
                          Avg ₹{(stat.avgStipend / 1000).toFixed(0)}K
                        </span>
                        <span className="text-xs font-bold text-primary-800">{stat.count}</span>
                      </div>
                    </div>
                    <div className="w-full h-1.5 bg-surface-muted rounded-full overflow-hidden">
                      <motion.div
                        className="h-full bg-accent rounded-full"
                        initial={{ width: 0 }}
                        animate={{ width: `${(stat.count / maxCount) * 100}%` }}
                        transition={{ duration: 0.6, delay: 0.1 }}
                      />
                    </div>
                  </div>
                </div>
              );
            })}
        </div>
      </div>

      {/* Stipend Distribution */}
      <div>
        <p className="section-header">Stipend Distribution</p>
        <div className="flex items-end gap-2 h-32">
          {analytics.stipendDistribution.map((bucket) => {
            const maxCount = Math.max(...analytics.stipendDistribution.map((b) => b.count));
            const height = maxCount > 0 ? (bucket.count / maxCount) * 100 : 0;
            return (
              <div key={bucket.range} className="flex-1 flex flex-col items-center gap-1">
                <span className="text-[9px] font-bold text-primary-600">{bucket.count}</span>
                <motion.div
                  className="w-full bg-accent/80 rounded-t-lg"
                  initial={{ height: 0 }}
                  animate={{ height: `${height}%` }}
                  transition={{ duration: 0.5, delay: 0.1 }}
                  style={{ minHeight: bucket.count > 0 ? '4px' : '0px' }}
                />
                <span className="text-[8px] font-medium text-primary-400 text-center leading-tight">
                  {bucket.range}
                </span>
              </div>
            );
          })}
        </div>
      </div>

      {/* Application Timeline */}
      <div>
        <p className="section-header">14-Day Activity</p>
        <div className="flex items-end gap-1 h-24">
          {analytics.applicationTimeline.map((entry, idx) => {
            const maxVal = Math.max(...analytics.applicationTimeline.map((e) => e.applied));
            const height = maxVal > 0 ? (entry.applied / maxVal) * 100 : 0;
            return (
              <div key={idx} className="flex-1 flex flex-col items-center gap-0.5">
                <motion.div
                  className="w-full bg-status-info/60 rounded-t"
                  initial={{ height: 0 }}
                  animate={{ height: `${height}%` }}
                  transition={{ duration: 0.4, delay: idx * 0.02 }}
                  style={{ minHeight: entry.applied > 0 ? '3px' : '0px' }}
                />
                {idx % 3 === 0 && (
                  <span className="text-[7px] text-primary-400">
                    {new Date(entry.date).getDate()}
                  </span>
                )}
              </div>
            );
          })}
        </div>
      </div>

      <div className="h-4" />
    </div>
  );
}

// ===== METRIC CARD =====
function MetricCard({
  icon, label, value, color,
}: {
  icon: React.ReactNode; label: string; value: string; color: string;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      className={`${color} rounded-2xl p-4 border border-surface-border`}
    >
      <div className="flex items-center gap-2 mb-2">{icon}</div>
      <p className="text-xl font-bold text-primary-900">{value}</p>
      <p className="text-[10px] font-medium text-primary-500 mt-0.5">{label}</p>
    </motion.div>
  );
}
