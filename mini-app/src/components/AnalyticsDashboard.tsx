// ============================================================
// ANALYTICS DASHBOARD — Premium Stats & Insights v3.0
// Fully scrollable, real data, professional charts
// ============================================================

import React, { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import {
  BarChart3, TrendingUp, Target, Users, Briefcase, CheckCircle2,
  XCircle, Send, Clock, Award, Database, Globe,
  Zap, Activity, PieChart, RefreshCw
} from 'lucide-react';
import { useAnalytics } from '@/hooks/useHooks';
import { SOURCE_CONFIG } from '@/utils/constants';
import { formatNumber } from '@/utils/helpers';
import { useAppStore } from '@/store/useAppStore';
import { fetchCanonicalCount } from '@/services/api';

export default function AnalyticsDashboard() {
  const { data: response, isLoading, refetch } = useAnalytics();
  const analytics = response?.data;
  const { appliedIds, viewedIds, dismissedIds } = useAppStore();
  const [refreshing, setRefreshing] = useState(false);
  const [canonicalCount, setCanonicalCount] = useState<number>(0);

  // Fetch canonical count for consistent display
  useEffect(() => {
    fetchCanonicalCount().then(resp => {
      if (resp.success && resp.data?.canonical_count) {
        setCanonicalCount(resp.data.canonical_count);
      }
    }).catch(() => {});
  }, []);

  const handleRefresh = async () => {
    setRefreshing(true);
    await refetch();
    setTimeout(() => setRefreshing(false), 500);
  };

  if (isLoading || !analytics) {
    return (
      <div className="px-5 py-8" style={{ paddingBottom: '120px' }}>
        <div className="space-y-4">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="skeleton h-24 rounded-2xl" />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="px-4 py-4 space-y-4" style={{ paddingBottom: '120px' }} id="analytics">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <BarChart3 className="w-5 h-5" style={{ color: '#0a0a0a' }} />
          <h2 className="text-base font-bold text-primary-900">Analytics Dashboard</h2>
        </div>
        <button
          onClick={handleRefresh}
          className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-[11px] font-medium text-primary-500 hover:text-primary-700 hover:bg-primary-50 transition-all"
        >
          <RefreshCw className={`w-3 h-3 ${refreshing ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {/* Key Metrics Grid */}
      <div className="grid grid-cols-2 gap-3">
        <MetricCard
          icon={<Briefcase className="w-5 h-5 text-blue-500" />}
          label="Total Listings"
          value={formatNumber(canonicalCount > 0 ? canonicalCount : analytics.totalListings)}
          bg="#eff6ff"
          accent="#3b82f6"
        />
        <MetricCard
          icon={<Send className="w-5 h-5" style={{ color: '#0a0a0a' }} />}
          label="Applied"
          value={Math.max(analytics.totalApplied, appliedIds.size).toString()}
          bg="#f3f4f6"
          accent="#0a0a0a"
        />
        <MetricCard
          icon={<CheckCircle2 className="w-5 h-5 text-emerald-500" />}
          label="Shortlisted"
          value={analytics.totalShortlisted.toString()}
          bg="#ecfdf5"
          accent="#059669"
        />
        <MetricCard
          icon={<Award className="w-5 h-5 text-amber-500" />}
          label="Offers"
          value={analytics.totalOffers.toString()}
          bg="#fffbeb"
          accent="#d97706"
        />
      </div>

      {/* Your Activity Summary */}
      <div className="rounded-2xl p-4" style={{ background: '#f8f9fa', border: '1px solid #e5e7eb' }}>
        <div className="flex items-center gap-2 mb-3">
          <Activity className="w-4 h-4 text-primary-500" />
          <h3 className="text-xs font-bold text-primary-800">Your Activity</h3>
        </div>
        <div className="grid grid-cols-3 gap-3">
          <div className="text-center">
            <p className="text-lg font-bold text-primary-900">{appliedIds.size}</p>
            <p className="text-[10px] text-primary-400 font-medium">Applied</p>
          </div>
          <div className="text-center">
            <p className="text-lg font-bold text-primary-900">{viewedIds.size}</p>
            <p className="text-[10px] text-primary-400 font-medium">Viewed</p>
          </div>
          <div className="text-center">
            <p className="text-lg font-bold text-primary-900">{dismissedIds.size}</p>
            <p className="text-[10px] text-primary-400 font-medium">Dismissed</p>
          </div>
        </div>
      </div>

      {/* Success Rate Card */}
      <div className="rounded-2xl p-5 text-white" style={{ background: 'var(--gradient-dark)' }}>
        <div className="flex items-center justify-between mb-3">
          <span className="text-xs font-medium text-white/70">Overall Success Rate</span>
          <TrendingUp className="w-4 h-4 text-white/50" />
        </div>
        <p className="text-3xl font-bold">{analytics.successRate}%</p>
        <div className="w-full h-2 bg-white/15 rounded-full mt-3">
          <div
            className="h-full bg-white rounded-full transition-all duration-700"
            style={{ width: `${Math.min(analytics.successRate, 100)}%` }}
          />
        </div>
        <div className="flex justify-between mt-2 text-[10px] text-white/50">
          <span>Avg Response: {analytics.avgResponseTime || 'N/A'} days</span>
          <span>{analytics.totalRejected} rejected</span>
        </div>
      </div>

      {/* Top Sources */}
      {analytics.topSources && analytics.topSources.length > 0 && (
        <div className="rounded-2xl p-4" style={{ background: '#ffffff', border: '1px solid #e5e7eb', boxShadow: '0 1px 4px rgba(0,0,0,0.04)' }}>
          <div className="flex items-center gap-2 mb-3">
            <Globe className="w-4 h-4 text-primary-500" />
            <h3 className="text-xs font-bold text-primary-800">Top Sources by Listings</h3>
          </div>
          <div className="space-y-2.5">
            {analytics.topSources
              .sort((a, b) => b.count - a.count)
              .slice(0, 8)
              .map((stat) => {
                const config = SOURCE_CONFIG[stat.source];
                if (!config) return null;
                const maxCount = analytics.topSources[0]?.count || 1;
                return (
                  <div key={stat.source} className="flex items-center gap-3">
                    <div className="w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0"
                      style={{ backgroundColor: config.color + '12' }}>
                      <span className="text-[10px] font-bold" style={{ color: config.color }}>
                        {config.name.charAt(0)}
                      </span>
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between mb-0.5">
                        <span className="text-[11px] font-semibold text-primary-700">{config.name}</span>
                        <span className="text-[11px] font-bold text-primary-800">{stat.count}</span>
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
      )}

      {/* Top Categories */}
      {analytics.topCategories && analytics.topCategories.length > 0 && (
        <div className="rounded-2xl p-4" style={{ background: '#ffffff', border: '1px solid #e5e7eb', boxShadow: '0 1px 4px rgba(0,0,0,0.04)' }}>
          <div className="flex items-center gap-2 mb-3">
            <PieChart className="w-4 h-4 text-primary-500" />
            <h3 className="text-xs font-bold text-primary-800">Top Categories</h3>
          </div>
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
                        <span className="text-[11px] font-semibold text-primary-700 capitalize">{stat.category}</span>
                        <div className="flex items-center gap-2">
                          {stat.avgStipend > 0 && (
                            <span className="text-[10px] text-primary-400">
                              Avg {(stat.avgStipend / 1000).toFixed(0)}K
                            </span>
                          )}
                          <span className="text-[11px] font-bold text-primary-800">{stat.count}</span>
                        </div>
                      </div>
                      <div className="w-full h-1.5 bg-surface-muted rounded-full overflow-hidden">
                        <motion.div
                          className="h-full rounded-full"
                          style={{ background: 'var(--gradient-accent)' }}
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
      )}

      {/* Stipend Distribution */}
      {analytics.stipendDistribution && analytics.stipendDistribution.length > 0 && (
        <div className="rounded-2xl p-4" style={{ background: '#ffffff', border: '1px solid #e5e7eb', boxShadow: '0 1px 4px rgba(0,0,0,0.04)' }}>
          <div className="flex items-center gap-2 mb-3">
            <Zap className="w-4 h-4 text-primary-500" />
            <h3 className="text-xs font-bold text-primary-800">Stipend Distribution</h3>
          </div>
          <div className="flex items-end gap-2 h-32">
            {analytics.stipendDistribution.map((bucket) => {
              const maxCount = Math.max(...analytics.stipendDistribution.map((b) => b.count));
              const height = maxCount > 0 ? (bucket.count / maxCount) * 100 : 0;
              return (
                <div key={bucket.range} className="flex-1 flex flex-col items-center gap-1">
                  <span className="text-[9px] font-bold text-primary-600">{bucket.count}</span>
                  <motion.div
                    className="w-full rounded-t-lg"
                    style={{ background: 'var(--gradient-accent)' }}
                    initial={{ height: 0 }}
                    animate={{ height: `${height}%` }}
                    transition={{ duration: 0.5, delay: 0.1 }}
                  />
                  <span className="text-[8px] font-medium text-primary-400 text-center leading-tight">
                    {bucket.range}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Application Timeline */}
      {analytics.applicationTimeline && analytics.applicationTimeline.length > 0 && (
        <div className="rounded-2xl p-4" style={{ background: '#ffffff', border: '1px solid #e5e7eb', boxShadow: '0 1px 4px rgba(0,0,0,0.04)' }}>
          <div className="flex items-center gap-2 mb-3">
            <Clock className="w-4 h-4 text-primary-500" />
            <h3 className="text-xs font-bold text-primary-800">14-Day Activity</h3>
          </div>
          <div className="flex items-end gap-1 h-24">
            {analytics.applicationTimeline.map((entry, idx) => {
              const maxVal = Math.max(...analytics.applicationTimeline.map((e) => e.applied));
              const height = maxVal > 0 ? (entry.applied / maxVal) * 100 : 0;
              return (
                <div key={idx} className="flex-1 flex flex-col items-center gap-0.5">
                  <motion.div
                    className="w-full bg-blue-400 rounded-t"
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
      )}

      {/* Data Source Info */}
      <div className="text-center py-4">
        <p className="text-[10px] text-primary-300">
          Data sourced from Operation First Mover backend & Supabase
        </p>
      </div>
    </div>
  );
}

// ===== METRIC CARD =====
function MetricCard({
  icon, label, value, bg, accent,
}: {
  icon: React.ReactNode; label: string; value: string; bg: string; accent: string;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      className="rounded-2xl p-4"
      style={{ background: bg, border: '1px solid #e5e7eb' }}
    >
      <div className="flex items-center gap-2 mb-2">{icon}</div>
      <p className="text-xl font-bold text-primary-900">{value}</p>
      <p className="text-[10px] font-medium text-primary-500 mt-0.5">{label}</p>
    </motion.div>
  );
}
