// ============================================================
// BATCH APPLY PANEL — Auto-Apply with Source Locking & Security
// ============================================================

import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  X, Play, Pause, CheckCircle2, AlertTriangle, Shield, Lock,
  Clock, Zap, ChevronRight, AlertOctagon, Info, Loader2,
  Eye, EyeOff, Key
} from 'lucide-react';
import { useAppStore } from '@/store/useAppStore';
import { useBatchApply, useCountdown } from '@/hooks/useHooks';
import { hapticFeedback, hapticNotification } from '@/utils/helpers';
import { SOURCE_CONFIG, RISK_WARNINGS, CREDENTIAL_REQUIREMENTS } from '@/utils/constants';
import type { InternshipSource } from '@/types';

export default function BatchApplyPanel() {
  const {
    isBatchPanelOpen, setBatchPanelOpen, selectedIds, lockedSource,
    batch, credentials, setCredentials, internships,
  } = useAppStore();
  const { executeBatch, isRunning, progress } = useBatchApply();
  const { remaining, isComplete } = useCountdown(batch.cooldownEndsAt);
  const [showCredForm, setShowCredForm] = useState(false);
  const [credFormData, setCredFormData] = useState<Record<string, string>>({});
  const [showPasswords, setShowPasswords] = useState<Record<string, boolean>>({});

  if (!isBatchPanelOpen) return null;

  const sourceConfig = lockedSource ? SOURCE_CONFIG[lockedSource] : null;
  const riskLevel = sourceConfig?.riskLevel || 'medium';
  const riskWarning = RISK_WARNINGS[riskLevel];
  const maxBatch = sourceConfig?.maxBatchSize || 5;
  const hasCreds = credentials.some((c) => c.source === lockedSource && c.isValid);
  const credReq = CREDENTIAL_REQUIREMENTS.find((c) => c.source === lockedSource);

  const selectedInternships = internships.filter((i) => selectedIds.has(i.id));

  const handleSaveCredentials = () => {
    if (!lockedSource) return;
    setCredentials({
      source: lockedSource,
      credentials: credFormData,
      isValid: true,
      lastVerified: new Date().toISOString(),
    });
    setShowCredForm(false);
    hapticNotification('success');
  };

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 z-50 bg-black/30 backdrop-blur-sm"
        onClick={() => setBatchPanelOpen(false)}
      >
        <motion.div
          initial={{ y: '100%' }}
          animate={{ y: 0 }}
          exit={{ y: '100%' }}
          transition={{ type: 'spring', damping: 30, stiffness: 300 }}
          className="absolute bottom-0 left-0 right-0 bg-white rounded-t-3xl max-h-[90vh] overflow-hidden flex flex-col"
          onClick={(e) => e.stopPropagation()}
        >
          {/* Handle */}
          <div className="flex justify-center pt-3 pb-1">
            <div className="w-10 h-1 bg-primary-200 rounded-full" />
          </div>

          {/* Header */}
          <div className="flex items-center justify-between px-5 py-3 border-b border-surface-border">
            <div className="flex items-center gap-2">
              <Zap className="w-5 h-5 text-accent" />
              <h2 className="text-base font-bold text-primary-900">Auto-Apply</h2>
            </div>
            <button onClick={() => setBatchPanelOpen(false)} className="p-1">
              <X className="w-5 h-5 text-primary-500" />
            </button>
          </div>

          <div className="flex-1 overflow-y-auto" style={{ paddingBottom: '24px' }}>
            {/* Source Lock Notice */}
            {lockedSource && (
              <div className="mx-5 mt-4 p-3 bg-accent/5 border border-accent/20 rounded-xl">
                <div className="flex items-center gap-2 mb-1">
                  <Lock className="w-4 h-4 text-accent" />
                  <span className="text-xs font-bold text-accent">Source Locked</span>
                </div>
                <p className="text-[11px] text-primary-600">
                  Applying to <span className="font-bold capitalize">{sourceConfig?.name}</span> only.
                  You can only select internships from one source per batch for safety.
                </p>
              </div>
            )}

            {/* Security Warning */}
            <div className={`mx-5 mt-3 p-3 rounded-xl border ${
              riskLevel === 'low' ? 'bg-status-success/5 border-status-success/20' :
              riskLevel === 'medium' ? 'bg-status-warning/5 border-status-warning/20' :
              riskLevel === 'high' ? 'bg-status-danger/5 border-status-danger/20' :
              'bg-status-danger/10 border-status-danger/30'
            }`}>
              <div className="flex items-center gap-2 mb-1">
                {riskLevel === 'low' ? <Shield className="w-4 h-4 text-status-success" /> :
                 riskLevel === 'medium' ? <AlertTriangle className="w-4 h-4 text-status-warning" /> :
                 <AlertOctagon className="w-4 h-4 text-status-danger" />}
                <span className={`text-xs font-bold uppercase ${
                  riskLevel === 'low' ? 'text-status-success' :
                  riskLevel === 'medium' ? 'text-status-warning' : 'text-status-danger'
                }`}>
                  {riskLevel} Risk
                </span>
              </div>
              <p className="text-[11px] text-primary-600">{riskWarning}</p>
            </div>

            {/* Batch Limits */}
            <div className="mx-5 mt-3 p-3 bg-surface-muted rounded-xl border border-surface-border">
              <div className="grid grid-cols-3 gap-3 text-center">
                <div>
                  <p className="text-lg font-bold text-accent">{selectedIds.size}</p>
                  <p className="text-[10px] text-primary-500 font-medium">Selected</p>
                </div>
                <div>
                  <p className="text-lg font-bold text-primary-800">{maxBatch}</p>
                  <p className="text-[10px] text-primary-500 font-medium">Max/Batch</p>
                </div>
                <div>
                  <p className="text-lg font-bold text-primary-800">{sourceConfig?.cooldownMinutes || 15}m</p>
                  <p className="text-[10px] text-primary-500 font-medium">Cooldown</p>
                </div>
              </div>
            </div>

            {selectedIds.size > maxBatch && (
              <div className="mx-5 mt-2 flex items-center gap-1.5 text-status-warning">
                <AlertTriangle className="w-3.5 h-3.5" />
                <span className="text-[11px] font-medium">
                  Max {maxBatch} per batch. Only first {maxBatch} will be processed.
                </span>
              </div>
            )}

            {/* Credentials Section */}
            <div className="mx-5 mt-4">
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <Key className="w-4 h-4 text-primary-500" />
                  <span className="text-xs font-bold text-primary-800">Credentials</span>
                </div>
                {hasCreds ? (
                  <span className="flex items-center gap-1 text-[10px] font-bold text-status-success">
                    <CheckCircle2 className="w-3 h-3" /> Saved
                  </span>
                ) : (
                  <span className="text-[10px] font-bold text-status-warning">Required</span>
                )}
              </div>

              {!hasCreds && !showCredForm && (
                <button
                  onClick={() => { setShowCredForm(true); hapticFeedback('light'); }}
                  className="w-full py-3 bg-surface-muted border border-dashed border-primary-300 rounded-xl text-xs font-semibold text-primary-600 hover:bg-surface-light transition-all"
                >
                  + Add {sourceConfig?.name || 'Platform'} Credentials
                </button>
              )}

              {showCredForm && credReq && (
                <motion.div
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: 'auto' }}
                  className="bg-surface-muted p-4 rounded-xl border border-surface-border"
                >
                  <p className="text-[11px] text-primary-500 mb-3">{credReq.notes}</p>
                  {credReq.fields.map((field) => (
                    <div key={field.key} className="mb-3">
                      <label className="text-[10px] font-semibold text-primary-600 uppercase mb-1 block">
                        {field.label} {field.required && <span className="text-status-danger">*</span>}
                      </label>
                      <div className="relative">
                        <input
                          type={field.type === 'password' && !showPasswords[field.key] ? 'password' : 'text'}
                          placeholder={field.placeholder}
                          value={credFormData[field.key] || ''}
                          onChange={(e) => setCredFormData({ ...credFormData, [field.key]: e.target.value })}
                          className="input-field text-sm pr-10"
                        />
                        {field.type === 'password' && (
                          <button
                            onClick={() => setShowPasswords({ ...showPasswords, [field.key]: !showPasswords[field.key] })}
                            className="absolute right-3 top-1/2 -translate-y-1/2 text-primary-400"
                          >
                            {showPasswords[field.key] ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                          </button>
                        )}
                      </div>
                      {field.helpText && (
                        <p className="text-[10px] text-primary-400 mt-1">{field.helpText}</p>
                      )}
                    </div>
                  ))}
                  <div className="flex gap-2">
                    <button onClick={handleSaveCredentials} className="btn-primary text-xs flex-1 py-2">
                      Save Credentials
                    </button>
                    <button onClick={() => setShowCredForm(false)} className="btn-secondary text-xs py-2">
                      Cancel
                    </button>
                  </div>
                </motion.div>
              )}
            </div>

            {/* Selected Internships Preview */}
            <div className="mx-5 mt-4">
              <p className="section-header">Selected Internships</p>
              <div className="space-y-2">
                {selectedInternships.slice(0, 10).map((item, idx) => (
                  <div key={item.id} className="flex items-center gap-3 p-2.5 bg-surface-muted rounded-xl">
                    <span className="w-5 h-5 bg-accent rounded-md flex items-center justify-center text-white text-[10px] font-bold">
                      {idx + 1}
                    </span>
                    <div className="flex-1 min-w-0">
                      <p className="text-xs font-semibold text-primary-800 line-clamp-1">{item.title}</p>
                      <p className="text-[10px] text-primary-500">{item.company}</p>
                    </div>
                    <span className="text-xs font-bold text-stipend-high whitespace-nowrap">
                      {item.stipend > 0 ? `₹${(item.stipend/1000).toFixed(0)}K` : 'Unpaid'}
                    </span>
                  </div>
                ))}
                {selectedInternships.length > 10 && (
                  <p className="text-[11px] text-primary-400 text-center">
                    +{selectedInternships.length - 10} more
                  </p>
                )}
              </div>
            </div>

            {/* Batch Progress (when running) */}
            {batch.status === 'running' && (
              <div className="mx-5 mt-4 p-4 bg-accent/5 rounded-xl border border-accent/20">
                <div className="flex items-center gap-2 mb-2">
                  <Loader2 className="w-4 h-4 text-accent animate-spin" />
                  <span className="text-xs font-bold text-accent">Applying...</span>
                  <span className="text-xs text-primary-500 ml-auto">
                    {batch.currentIndex + 1} / {batch.totalCount}
                  </span>
                </div>
                <div className="w-full h-2 bg-primary-100 rounded-full overflow-hidden">
                  <motion.div
                    className="h-full bg-accent rounded-full"
                    initial={{ width: 0 }}
                    animate={{ width: `${progress}%` }}
                    transition={{ duration: 0.5 }}
                  />
                </div>
                <div className="flex justify-between mt-2 text-[10px] text-primary-500">
                  <span className="text-status-success font-medium">{batch.successCount} success</span>
                  <span className="text-status-danger font-medium">{batch.failCount} failed</span>
                </div>
              </div>
            )}

            {/* Cooldown Timer */}
            {batch.status === 'cooldown' && !isComplete && (
              <div className="mx-5 mt-4 p-4 bg-status-warning/5 rounded-xl border border-status-warning/20">
                <div className="flex items-center gap-2 mb-1">
                  <Clock className="w-4 h-4 text-status-warning" />
                  <span className="text-xs font-bold text-status-warning">Cooldown Active</span>
                </div>
                <p className="text-[11px] text-primary-600">
                  Next batch unlocks in <span className="font-bold text-accent">{remaining}</span>
                </p>
                <p className="text-[10px] text-primary-400 mt-1">
                  Cooldown protects your account from rate limiting and detection.
                </p>
              </div>
            )}

            {/* Batch Complete */}
            {batch.status === 'cooldown' && isComplete && (
              <div className="mx-5 mt-4 p-4 bg-status-success/5 rounded-xl border border-status-success/20">
                <div className="flex items-center gap-2 mb-1">
                  <CheckCircle2 className="w-4 h-4 text-status-success" />
                  <span className="text-xs font-bold text-status-success">Batch Complete — Ready for Next</span>
                </div>
                <p className="text-[11px] text-primary-600">
                  {batch.successCount} applications submitted successfully.
                  Select new internships to start another batch.
                </p>
              </div>
            )}
          </div>

          {/* Action Button */}
          <div className="sticky bottom-0 left-0 right-0 p-4 bg-white border-t border-[#e5e7eb]" style={{ paddingBottom: 'calc(1rem + env(safe-area-inset-bottom, 0px))' }}>
            {batch.status === 'running' ? (
              <button
                onClick={() => { useAppStore.getState().cancelBatch(); hapticFeedback('medium'); }}
                className="w-full py-3 bg-status-danger text-white rounded-xl font-semibold text-sm flex items-center justify-center gap-2"
              >
                <Pause className="w-4 h-4" /> Pause Batch
              </button>
            ) : batch.status === 'cooldown' && !isComplete ? (
              <button disabled className="w-full py-3 bg-primary-200 text-primary-500 rounded-xl font-semibold text-sm cursor-not-allowed flex items-center justify-center gap-2">
                <Lock className="w-4 h-4" /> Locked — {remaining}
              </button>
            ) : (
              <button
                onClick={() => { executeBatch(); hapticFeedback('heavy'); }}
                disabled={selectedIds.size === 0 || !hasCreds}
                className={`w-full py-3 rounded-xl font-semibold text-sm flex items-center justify-center gap-2 transition-all ${
                  selectedIds.size > 0 && hasCreds
                    ? 'bg-accent text-white hover:bg-accent-light'
                    : 'bg-primary-200 text-primary-500 cursor-not-allowed'
                }`}
              >
                <Play className="w-4 h-4" />
                {!hasCreds ? 'Add Credentials First' : `Apply to ${Math.min(selectedIds.size, maxBatch)} Internships`}
              </button>
            )}
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}
