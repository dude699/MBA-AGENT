// ============================================================
// SKELETON LOADERS — Loading States
// ============================================================

import React from 'react';

export function InternshipCardSkeleton() {
  return (
    <div className="bg-white rounded-2xl p-4 space-y-3 animate-pulse" style={{ border: '1px solid rgba(0,0,0,0.05)', boxShadow: '0 1px 4px rgba(0,0,0,0.03)' }}>
      {/* Top row */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="skeleton w-20 h-5 rounded-md" />
          <div className="skeleton w-14 h-4 rounded-md" />
        </div>
        <div className="flex items-center gap-2">
          <div className="skeleton w-16 h-5 rounded-md" />
          <div className="skeleton w-5 h-5 rounded-md" />
        </div>
      </div>

      {/* Company + Title */}
      <div className="space-y-1.5">
        <div className="flex items-center gap-2">
          <div className="skeleton w-6 h-6 rounded-lg" />
          <div className="skeleton w-28 h-4 rounded-md" />
          <div className="skeleton w-8 h-4 rounded-md" />
        </div>
        <div className="skeleton w-3/4 h-5 rounded-md" />
      </div>

      {/* Details */}
      <div className="flex gap-3">
        <div className="skeleton w-16 h-4 rounded-md" />
        <div className="skeleton w-20 h-4 rounded-md" />
        <div className="skeleton w-24 h-4 rounded-md" />
      </div>

      {/* Skills */}
      <div className="flex gap-1.5">
        <div className="skeleton w-14 h-5 rounded-md" />
        <div className="skeleton w-12 h-5 rounded-md" />
        <div className="skeleton w-16 h-5 rounded-md" />
        <div className="skeleton w-10 h-5 rounded-md" />
      </div>

      {/* Bottom */}
      <div className="pt-2.5 flex items-center justify-between" style={{ borderTop: '1px solid rgba(0,0,0,0.04)' }}>
        <div className="flex gap-3">
          <div className="skeleton w-20 h-4 rounded-md" />
          <div className="skeleton w-20 h-4 rounded-md" />
          <div className="skeleton w-12 h-4 rounded-md" />
        </div>
        <div className="skeleton w-16 h-4 rounded-md" />
      </div>
    </div>
  );
}

export function ListSkeleton({ count = 5 }: { count?: number }) {
  return (
    <div className="space-y-3 px-4">
      {Array.from({ length: count }).map((_, i) => (
        <InternshipCardSkeleton key={i} />
      ))}
    </div>
  );
}

export function StatsSkeleton() {
  return (
    <div className="px-5 space-y-4 animate-pulse">
      <div className="grid grid-cols-2 gap-3">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="skeleton h-20 rounded-2xl" />
        ))}
      </div>
      <div className="skeleton h-28 rounded-2xl" />
      <div className="space-y-2">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="skeleton h-8 rounded-lg" />
        ))}
      </div>
    </div>
  );
}
