// ============================================================
// BATCH APPLY PANEL — v3.0: Real-time Portal Info Request System
// ============================================================
// Features:
//   - Dynamic form fields based on what portal needs
//   - Real-time info request during batch apply
//   - No hardcoded fields — adapts to portal requirements
//   - Saves & reuses user profile data across sessions
// ============================================================

import React, { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  X, Play, Pause, CheckCircle2, AlertTriangle, Shield, Lock,
  Clock, Zap, ChevronRight, AlertOctagon, Info, Loader2,
  Eye, EyeOff, Key, ExternalLink, Send, RotateCcw, User,
  FileText, Phone, Mail, MapPin, GraduationCap, Briefcase
} from 'lucide-react';
import { useAppStore } from '@/store/useAppStore';
import { useBatchApply, useCountdown } from '@/hooks/useHooks';
import { hapticFeedback, hapticNotification } from '@/utils/helpers';
import { SOURCE_CONFIG, RISK_WARNINGS, CREDENTIAL_REQUIREMENTS } from '@/utils/constants';
import type { InternshipSource } from '@/types';

// Portal-specific additional fields that may be requested during application
const PORTAL_EXTRA_FIELDS: Record<string, Array<{
  key: string; label: string; type: string; required: boolean;
  placeholder: string; helpText?: string; icon?: string;
}>> = {
  internshala: [
    { key: 'full_name', label: 'Full Name', type: 'text', required: true, placeholder: 'Your full name', icon: 'user' },
    { key: 'email', label: 'Email', type: 'email', required: true, placeholder: 'your@email.com', icon: 'mail' },
    { key: 'phone', label: 'Phone Number', type: 'tel', required: true, placeholder: '+91 9876543210', icon: 'phone' },
    { key: 'college', label: 'College/University', type: 'text', required: true, placeholder: 'IIM Ahmedabad', icon: 'graduation' },
    { key: 'degree', label: 'Degree', type: 'text', required: true, placeholder: 'MBA', icon: 'graduation' },
    { key: 'graduation_year', label: 'Graduation Year', type: 'text', required: true, placeholder: '2026', icon: 'graduation' },
    { key: 'cover_letter', label: 'Cover Letter (optional)', type: 'textarea', required: false, placeholder: 'Why are you interested in this role?', helpText: 'PRISM AI will auto-generate if left blank' },
    { key: 'availability', label: 'Available From', type: 'text', required: false, placeholder: 'Immediately / June 2026', icon: 'clock' },
  ],
  naukri: [
    { key: 'full_name', label: 'Full Name', type: 'text', required: true, placeholder: 'Your full name', icon: 'user' },
    { key: 'email', label: 'Email', type: 'email', required: true, placeholder: 'your@email.com', icon: 'mail' },
    { key: 'phone', label: 'Phone Number', type: 'tel', required: true, placeholder: '+91 9876543210', icon: 'phone' },
    { key: 'current_location', label: 'Current City', type: 'text', required: true, placeholder: 'Mumbai', icon: 'location' },
    { key: 'experience_years', label: 'Total Experience', type: 'text', required: false, placeholder: '0 years (Fresher)', icon: 'briefcase' },
    { key: 'resume_headline', label: 'Resume Headline', type: 'text', required: false, placeholder: 'MBA Candidate | Data Analytics', helpText: 'Brief headline for your profile' },
  ],
  linkedin: [
    { key: 'linkedin_profile', label: 'LinkedIn Profile URL', type: 'text', required: true, placeholder: 'https://linkedin.com/in/yourname', icon: 'user' },
    { key: 'cover_letter', label: 'Cover Letter', type: 'textarea', required: false, placeholder: 'Brief intro for the recruiter', helpText: 'AI will personalize if left blank' },
  ],
  default: [
    { key: 'full_name', label: 'Full Name', type: 'text', required: true, placeholder: 'Your full name', icon: 'user' },
    { key: 'email', label: 'Email', type: 'email', required: true, placeholder: 'your@email.com', icon: 'mail' },
    { key: 'phone', label: 'Phone Number', type: 'tel', required: false, placeholder: '+91 9876543210', icon: 'phone' },
    { key: 'college', label: 'College/University', type: 'text', required: false, placeholder: 'Your institution', icon: 'graduation' },
  ],
};

const FIELD_ICONS: Record<string, React.ReactNode> = {
  user: <User className="w-3.5 h-3.5" />,
  mail: <Mail className="w-3.5 h-3.5" />,
  phone: <Phone className="w-3.5 h-3.5" />,
  location: <MapPin className="w-3.5 h-3.5" />,
  graduation: <GraduationCap className="w-3.5 h-3.5" />,
  briefcase: <Briefcase className="w-3.5 h-3.5" />,
  clock: <Clock className="w-3.5 h-3.5" />,
  file: <FileText className="w-3.5 h-3.5" />,
};

// Local storage key for persisting user profile
const PROFILE_STORAGE_KEY = 'prism_user_apply_profile';

function loadSavedProfile(): Record<string, string> {
  try {
    const saved = localStorage.getItem(PROFILE_STORAGE_KEY);
    return saved ? JSON.parse(saved) : {};
  } catch { return {}; }
}

function saveProfile(data: Record<string, string>) {
  try {
    localStorage.setItem(PROFILE_STORAGE_KEY, JSON.stringify(data));
  } catch { /* ignore */ }
}

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
  const [showExtraInfo, setShowExtraInfo] = useState(false);
  const [extraInfoData, setExtraInfoData] = useState<Record<string, string>>(() => loadSavedProfile());
  const [extraInfoSaved, setExtraInfoSaved] = useState(false);

  // Load saved profile on mount
  useEffect(() => {
    const saved = loadSavedProfile();
    if (Object.keys(saved).length > 0) {
      setExtraInfoData(saved);
      setExtraInfoSaved(true);
    }
  }, []);

  if (!isBatchPanelOpen) return null;

  const normalizedLockedSource = (lockedSource || '').toLowerCase();
  const sourceConfig = lockedSource ? (SOURCE_CONFIG[normalizedLockedSource] || SOURCE_CONFIG[lockedSource]) : null;
  const riskLevel = sourceConfig?.riskLevel || 'medium';
  const riskWarning = RISK_WARNINGS[riskLevel];
  const maxBatch = sourceConfig?.maxBatchSize || 5;
  const hasCreds = credentials.some((c) => (c.source || '').toLowerCase() === normalizedLockedSource && c.isValid);
  const credReq = CREDENTIAL_REQUIREMENTS.find((c) => (c.source || '').toLowerCase() === normalizedLockedSource);
  const isDirectApplySource = !credReq;
  const canApply = true;

  // Get portal-specific extra fields
  const portalFields = PORTAL_EXTRA_FIELDS[normalizedLockedSource] || PORTAL_EXTRA_FIELDS.default;
  const hasRequiredEmpty = portalFields.some(f => f.required && !extraInfoData[f.key]);

  // Search both store internships AND supabase cache for selected items
  const sbCache = ((window as any).__sbJobsCache || []) as any[];
  const allKnownJobs = [...internships, ...sbCache];
  const seenIds = new Set<string>();
  const selectedInternships = allKnownJobs.filter((i) => {
    if (!selectedIds.has(i.id) || seenIds.has(i.id)) return false;
    seenIds.add(i.id);
    return true;
  });
  const applyCount = Math.min(selectedIds.size, maxBatch);

  const handleSaveCredentials = () => {
    if (!lockedSource) return;
    setCredentials({
      source: normalizedLockedSource,
      credentials: credFormData,
      isValid: true,
      lastVerified: new Date().toISOString(),
    });
    setShowCredForm(false);
    hapticNotification('success');
  };

  const handleSaveExtraInfo = () => {
    saveProfile(extraInfoData);
    setExtraInfoSaved(true);
    setShowExtraInfo(false);
    hapticNotification('success');
  };

  const handleStartApply = () => {
    // If required fields are missing, show the extra info form first
    if (hasRequiredEmpty && !extraInfoSaved) {
      setShowExtraInfo(true);
      hapticFeedback('medium');
      return;
    }
    // Include extra info in the apply request
    const store = useAppStore.getState();
    if (Object.keys(extraInfoData).length > 0) {
      // Merge extra info into credentials so backend receives it
      const existingCreds = store.credentials.find(c => (c.source || '').toLowerCase() === normalizedLockedSource);
      store.setCredentials({
        source: normalizedLockedSource || '',
        credentials: {
          ...(existingCreds?.credentials || {}),
          ...credFormData,
          ...extraInfoData,
        },
        isValid: true,
        lastVerified: new Date().toISOString(),
      });
    }
    executeBatch();
    hapticFeedback('heavy');
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

          <div className="flex-1 overflow-y-auto" style={{ paddingBottom: '8px' }}>
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

            {/* ===== PORTAL EXTRA INFO SECTION (v3.0) ===== */}
            <div className="mx-5 mt-4">
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <User className="w-4 h-4 text-primary-500" />
                  <span className="text-xs font-bold text-primary-800">Your Application Info</span>
                </div>
                {extraInfoSaved ? (
                  <button
                    onClick={() => setShowExtraInfo(!showExtraInfo)}
                    className="flex items-center gap-1 text-[10px] font-bold text-status-success"
                  >
                    <CheckCircle2 className="w-3 h-3" /> Saved
                    <span className="text-primary-400 ml-1">(edit)</span>
                  </button>
                ) : (
                  <span className="text-[10px] font-bold text-status-warning">Fill to apply</span>
                )}
              </div>

              <p className="text-[10px] text-primary-400 mb-2">
                Portals may need this info during application. Saved across sessions.
              </p>

              {(showExtraInfo || (!extraInfoSaved && portalFields.some(f => f.required))) && (
                <motion.div
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: 'auto' }}
                  className="bg-surface-muted p-4 rounded-xl border border-surface-border"
                >
                  <div className="flex items-center gap-2 mb-3">
                    <FileText className="w-4 h-4 text-accent" />
                    <span className="text-xs font-bold text-accent">
                      {lockedSource ? `${sourceConfig?.name || 'Portal'} Application Fields` : 'Application Fields'}
                    </span>
                  </div>

                  {portalFields.map((field) => (
                    <div key={field.key} className="mb-3">
                      <label className="text-[10px] font-semibold text-primary-600 uppercase mb-1 flex items-center gap-1">
                        {field.icon && FIELD_ICONS[field.icon]}
                        {field.label}
                        {field.required && <span className="text-status-danger">*</span>}
                      </label>
                      {field.type === 'textarea' ? (
                        <textarea
                          placeholder={field.placeholder}
                          value={extraInfoData[field.key] || ''}
                          onChange={(e) => setExtraInfoData({ ...extraInfoData, [field.key]: e.target.value })}
                          rows={3}
                          className="input-field text-sm resize-none"
                        />
                      ) : (
                        <input
                          type={field.type}
                          placeholder={field.placeholder}
                          value={extraInfoData[field.key] || ''}
                          onChange={(e) => setExtraInfoData({ ...extraInfoData, [field.key]: e.target.value })}
                          className="input-field text-sm"
                        />
                      )}
                      {field.helpText && (
                        <p className="text-[10px] text-primary-400 mt-1">{field.helpText}</p>
                      )}
                    </div>
                  ))}

                  <button
                    onClick={handleSaveExtraInfo}
                    className="w-full py-2.5 bg-accent text-white rounded-xl text-xs font-semibold active:scale-[0.98] transition-transform"
                  >
                    Save & Continue
                  </button>
                </motion.div>
              )}
            </div>

            {/* Credentials Section */}
            <div className="mx-5 mt-4">
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <Key className="w-4 h-4 text-primary-500" />
                  <span className="text-xs font-bold text-primary-800">Portal Credentials</span>
                </div>
                {hasCreds ? (
                  <span className="flex items-center gap-1 text-[10px] font-bold text-status-success">
                    <CheckCircle2 className="w-3 h-3" /> Saved
                  </span>
                ) : isDirectApplySource ? (
                  <span className="flex items-center gap-1 text-[10px] font-bold text-blue-600">
                    <ExternalLink className="w-3 h-3" /> Direct Apply
                  </span>
                ) : (
                  <span className="text-[10px] font-bold text-status-warning">Required</span>
                )}
              </div>

              {isDirectApplySource && !hasCreds && (
                <div className="p-3 bg-emerald-50 border border-emerald-100 rounded-xl mb-2">
                  <div className="flex items-center gap-2 mb-1">
                    <Send className="w-3.5 h-3.5 text-emerald-600" />
                    <span className="text-[11px] font-bold text-emerald-700">Auto-Apply Ready</span>
                  </div>
                  <p className="text-[11px] text-emerald-600">
                    PRISM will submit applications and generate cover letters automatically.
                    {applyCount} application{applyCount > 1 ? 's' : ''} will be processed.
                  </p>
                </div>
              )}

              {!isDirectApplySource && !hasCreds && !showCredForm && (
                <button
                  onClick={() => { setShowCredForm(true); hapticFeedback('light'); }}
                  className="w-full py-3 bg-surface-muted border border-dashed border-primary-300 rounded-xl text-xs font-semibold text-primary-600 hover:bg-surface-light transition-all active:scale-[0.98]"
                >
                  + Add {sourceConfig?.name || 'Platform'} Login Credentials
                </button>
              )}

              {!isDirectApplySource && hasCreds && !showCredForm && (
                <div className="p-3 bg-emerald-50 border border-emerald-100 rounded-xl mb-2">
                  <div className="flex items-center gap-2 mb-1">
                    <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" />
                    <span className="text-[11px] font-bold text-emerald-700">Auto-Apply Ready</span>
                  </div>
                  <p className="text-[11px] text-emerald-600">
                    PRISM will generate personalized cover letters and submit applications to {sourceConfig?.name || 'the portal'} automatically. Failed applications will fall back to manual apply.
                  </p>
                </div>
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
                    <span className="w-5 h-5 bg-accent rounded-md flex items-center justify-center text-white text-[10px] font-bold flex-shrink-0">
                      {idx + 1}
                    </span>
                    <div className="flex-1 min-w-0">
                      <p className="text-xs font-semibold text-primary-800 line-clamp-1">{item.title}</p>
                      <p className="text-[10px] text-primary-500 line-clamp-1">{item.company}</p>
                    </div>
                    <span className="text-xs font-bold text-stipend-high whitespace-nowrap flex-shrink-0">
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
                  <span className="text-xs font-bold text-status-success">Batch Complete</span>
                </div>
                <p className="text-[11px] text-primary-600">
                  {batch.successCount} applications submitted successfully.
                  Select new internships to start another batch.
                </p>
              </div>
            )}
          </div>

          {/* ============================================ */}
          {/* ACTION BUTTON — Always visible, sticky bottom */}
          {/* ============================================ */}
          <div
            className="flex-shrink-0 p-4 bg-white border-t border-surface-border"
            style={{ paddingBottom: 'calc(1rem + env(safe-area-inset-bottom, 0px))' }}
          >
            {batch.status === 'running' ? (
              <button
                onClick={() => { useAppStore.getState().cancelBatch(); hapticFeedback('medium'); }}
                className="w-full py-3.5 bg-red-600 text-white rounded-xl font-semibold text-sm flex items-center justify-center gap-2 active:scale-[0.98] transition-transform"
              >
                <Pause className="w-4 h-4" /> Pause Batch
              </button>
            ) : batch.status === 'cooldown' && !isComplete ? (
              <button
                disabled
                className="w-full py-3.5 bg-gray-200 text-gray-500 rounded-xl font-semibold text-sm cursor-not-allowed flex items-center justify-center gap-2"
              >
                <Lock className="w-4 h-4" /> Cooldown — {remaining}
              </button>
            ) : (
              <button
                onClick={handleStartApply}
                disabled={selectedIds.size === 0 || !canApply}
                className={`w-full py-3.5 rounded-xl font-semibold text-sm flex items-center justify-center gap-2 transition-all active:scale-[0.98] ${
                  selectedIds.size > 0 && canApply
                    ? 'bg-[#0a0a0a] text-white shadow-lg hover:shadow-xl'
                    : 'bg-gray-200 text-gray-500 cursor-not-allowed'
                }`}
              >
                <>
                  <Send className="w-4 h-4" />
                  {hasRequiredEmpty && !extraInfoSaved
                    ? 'Fill Info & Apply'
                    : `Apply to ${applyCount} ${applyCount === 1 ? 'Internship' : 'Internships'}`
                  }
                </>
              </button>
            )}

            {/* Quick info below button */}
            {selectedIds.size > 0 && canApply && batch.status === 'idle' && (
              <p className="text-[10px] text-primary-400 text-center mt-2">
                PRISM records applications & auto-submits where supported
              </p>
            )}
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}
