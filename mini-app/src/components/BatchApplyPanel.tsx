// ============================================================
// BATCH APPLY PANEL — v9.0: TRUE Single-Click Auto-Apply
// ============================================================
// PRISM v9.0: Zero manual intervention.
//   1. User fills profile ONCE (saved permanently)
//   2. User logs into Internshala ONCE (session lasts weeks)
//   3. Then just: select jobs → click "Apply" → DONE
//
// Key innovations:
//   - Persistent login state across sessions (localStorage)
//   - Auto-fills credentials from saved profile
//   - Login happens inline without leaving the panel
//   - Profile & creds merge automatically for backend
//   - No confusing session cookie instructions
// ============================================================

import React, { useState, useEffect, useCallback } from 'react';
import {
  X, Play, Pause, CheckCircle2, AlertTriangle, Shield, Lock,
  Clock, Zap, ChevronRight, AlertOctagon, Info,
  Eye, EyeOff, Key, ExternalLink, Send, RotateCcw, User,
  FileText, Phone, Mail, MapPin, GraduationCap, Briefcase,
  Copy, RefreshCcw, Cookie, Loader2, LogIn, ChevronDown,
  ChevronUp, Sparkles
} from 'lucide-react';
import { useAppStore } from '@/store/useAppStore';
import { useBatchApply, useCountdown } from '@/hooks/useHooks';
import { hapticFeedback, hapticNotification } from '@/utils/helpers';
import { SOURCE_CONFIG, RISK_WARNINGS, CREDENTIAL_REQUIREMENTS } from '@/utils/constants';
import { validateSessionCookie, loginToInternshala } from '@/services/api';
import type { InternshipSource } from '@/types';
import toast from 'react-hot-toast';

// Persistent storage keys
const PROFILE_KEY = 'prism_user_apply_profile';
const CREDS_KEY = 'prism_portal_creds';
const LOGIN_STATE_KEY = 'prism_login_state';

// Portal extra fields for profile
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
    { key: 'availability', label: 'Available From', type: 'text', required: false, placeholder: 'Immediately / June 2026', icon: 'clock' },
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

// === Persistent helpers ===
function loadSaved(key: string): Record<string, string> {
  try { const s = localStorage.getItem(key); return s ? JSON.parse(s) : {}; } catch { return {}; }
}
function savePersistent(key: string, data: Record<string, string>) {
  try { localStorage.setItem(key, JSON.stringify(data)); } catch {}
}
function loadLoginState(): { loggedIn: boolean; username: string; source: string } {
  try {
    const s = localStorage.getItem(LOGIN_STATE_KEY);
    return s ? JSON.parse(s) : { loggedIn: false, username: '', source: '' };
  } catch { return { loggedIn: false, username: '', source: '' }; }
}
function saveLoginState(state: { loggedIn: boolean; username: string; source: string }) {
  try { localStorage.setItem(LOGIN_STATE_KEY, JSON.stringify(state)); } catch {}
}

export default function BatchApplyPanel() {
  const {
    isBatchPanelOpen, setBatchPanelOpen, selectedIds, lockedSource,
    batch, credentials, setCredentials, internships,
  } = useAppStore();
  const { executeBatch, isRunning, progress } = useBatchApply();
  const { remaining, isComplete } = useCountdown(batch.cooldownEndsAt);

  // Profile data (name, email, phone, college etc.)
  const [profileData, setProfileData] = useState<Record<string, string>>(() => loadSaved(PROFILE_KEY));
  const [profileSaved, setProfileSaved] = useState(() => Object.keys(loadSaved(PROFILE_KEY)).length > 0);
  const [showProfileForm, setShowProfileForm] = useState(false);

  // Login credentials (portal email, password, captcha key)
  const [credData, setCredData] = useState<Record<string, string>>(() => loadSaved(CREDS_KEY));
  const [showLoginForm, setShowLoginForm] = useState(false);
  const [showPasswords, setShowPasswords] = useState<Record<string, boolean>>({});

  // Login state
  const [loginState, setLoginState] = useState(() => loadLoginState());
  const [isLoggingIn, setIsLoggingIn] = useState(false);

  // Advanced: session cookie
  const [showAdvanced, setShowAdvanced] = useState(false);

  // Load profile on mount
  useEffect(() => {
    const p = loadSaved(PROFILE_KEY);
    if (Object.keys(p).length > 0) { setProfileData(p); setProfileSaved(true); }
    const c = loadSaved(CREDS_KEY);
    if (Object.keys(c).length > 0) setCredData(c);
    setLoginState(loadLoginState());
  }, []);

  if (!isBatchPanelOpen) return null;

  const normalizedSource = (lockedSource || '').toLowerCase();
  const sourceConfig = lockedSource ? (SOURCE_CONFIG[normalizedSource] || SOURCE_CONFIG[lockedSource]) : null;
  const maxBatch = sourceConfig?.maxBatchSize || 5;
  const credReq = CREDENTIAL_REQUIREMENTS.find((c) => (c.source || '').toLowerCase() === normalizedSource);
  const isInternshala = normalizedSource === 'internshala';
  const isLoggedIn = loginState.loggedIn && loginState.source === normalizedSource;

  // Portal fields
  const portalFields = PORTAL_EXTRA_FIELDS[normalizedSource] || PORTAL_EXTRA_FIELDS.default;
  const hasRequiredProfileEmpty = portalFields.some(f => f.required && !profileData[f.key]);

  // Selected jobs
  const sbCache = ((window as any).__sbJobsCache || []) as any[];
  const allKnownJobs = [...internships, ...sbCache];
  const seenIds = new Set<string>();
  const selectedInternships = allKnownJobs.filter((i) => {
    if (!selectedIds.has(i.id) || seenIds.has(i.id)) return false;
    seenIds.add(i.id); return true;
  });
  const applyCount = Math.min(selectedIds.size, maxBatch);

  // === STEP CALCULATION ===
  // Step 1: Profile filled? Step 2: Logged in? Step 3: Ready to apply!
  const step = !profileSaved || hasRequiredProfileEmpty ? 1 : (!isLoggedIn && credReq) ? 2 : 3;

  // === HANDLERS ===
  const handleSaveProfile = () => {
    savePersistent(PROFILE_KEY, profileData);
    setProfileSaved(true);
    setShowProfileForm(false);
    hapticNotification('success');
    toast.success('Profile saved! This info is reused for all future applications.', { duration: 3000 });

    // Auto-populate login email from profile email
    if (profileData.email && !credData.email) {
      const updated = { ...credData, email: profileData.email };
      setCredData(updated);
      savePersistent(CREDS_KEY, updated);
    }
  };

  const handleLogin = async () => {
    const email = credData.email?.trim() || profileData.email?.trim();
    const password = credData.password?.trim();
    if (!email || !password) {
      toast.error('Enter your Internshala email & password');
      return;
    }

    setIsLoggingIn(true);
    toast.loading('Logging into Internshala...', { id: 'login' });

    try {
      const result = await loginToInternshala(
        email, password,
        credData.captcha_api_key?.trim() || '',
        'capsolver',
      );
      toast.dismiss('login');

      if (result.success && result.data?.session_valid) {
        const newState = { loggedIn: true, username: result.data.username || email, source: normalizedSource };
        setLoginState(newState);
        saveLoginState(newState);
        savePersistent(CREDS_KEY, credData);
        setShowLoginForm(false);

        // Also set credentials in the store for batch-apply
        setCredentials({
          source: normalizedSource,
          credentials: { ...credData, ...profileData, email, password },
          isValid: true,
          lastVerified: new Date().toISOString(),
        });

        toast.success(
          result.data.message || `Logged in as ${result.data.username || email}! Ready to auto-apply.`,
          { duration: 5000 }
        );
        hapticNotification('success');
      } else {
        const err = result.data?.message || result.error || 'Login failed';
        const needsKey = result.data?.needs_captcha_key;
        if (needsKey) {
          toast.error(
            'Internshala requires CAPTCHA for login. Add a capsolver.com API key (~$3/1000) below, OR paste your session cookie in Advanced.',
            { duration: 8000 }
          );
        } else {
          toast.error(err, { duration: 6000 });
        }
        hapticNotification('error');
      }
    } catch {
      toast.dismiss('login');
      toast.error('Connection error. Check your internet.');
    } finally {
      setIsLoggingIn(false);
    }
  };

  const handleValidateCookie = async () => {
    const cookie = credData.session_cookie?.trim();
    if (!cookie) return;

    setIsLoggingIn(true);
    toast.loading('Validating session cookie...', { id: 'validate' });

    try {
      const result = await validateSessionCookie(normalizedSource, cookie);
      toast.dismiss('validate');

      if (result.success && result.data?.valid) {
        const newState = { loggedIn: true, username: result.data.username || 'User', source: normalizedSource };
        setLoginState(newState);
        saveLoginState(newState);
        savePersistent(CREDS_KEY, credData);
        setShowLoginForm(false);
        setShowAdvanced(false);

        setCredentials({
          source: normalizedSource,
          credentials: { ...credData, ...profileData },
          isValid: true,
          lastVerified: new Date().toISOString(),
        });

        toast.success(`Session verified! Logged in as ${result.data.username || 'User'}`, { duration: 4000 });
        hapticNotification('success');
      } else {
        toast.error(result.data?.message || 'Session cookie expired or invalid', { duration: 5000 });
        hapticNotification('error');
      }
    } catch {
      toast.dismiss('validate');
      toast.error('Validation failed. Check your connection.');
    } finally {
      setIsLoggingIn(false);
    }
  };

  const handleLogout = () => {
    setLoginState({ loggedIn: false, username: '', source: '' });
    saveLoginState({ loggedIn: false, username: '', source: '' });
    toast.success('Logged out. You can log in again anytime.');
  };

  const handleStartApply = () => {
    // Ensure profile is filled
    if (hasRequiredProfileEmpty && !profileSaved) {
      setShowProfileForm(true);
      hapticFeedback('medium');
      return;
    }

    // Merge ALL data into credentials for the backend
    const store = useAppStore.getState();
    store.setCredentials({
      source: normalizedSource || '',
      credentials: { ...profileData, ...credData },
      isValid: true,
      lastVerified: new Date().toISOString(),
    });

    executeBatch();
    hapticFeedback('heavy');
  };

  return (
    <BatchPanelWrapper
      isOpen={isBatchPanelOpen}
      onClose={() => setBatchPanelOpen(false)}
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
          {isLoggedIn && (
            <span className="text-[10px] bg-emerald-100 text-emerald-700 px-2 py-0.5 rounded-full font-bold">
              Logged In
            </span>
          )}
        </div>
        <button onClick={() => setBatchPanelOpen(false)} className="p-1">
          <X className="w-5 h-5 text-primary-500" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto" style={{ paddingBottom: '8px' }}>

        {/* ===== STEP INDICATOR ===== */}
        <div className="mx-5 mt-4 flex items-center gap-1">
          {[1, 2, 3].map(s => (
            <div key={s} className="flex items-center gap-1 flex-1">
              <div className={`w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold transition-all ${
                s < step ? 'bg-emerald-500 text-white' : s === step ? 'bg-accent text-white' : 'bg-gray-100 text-gray-400'
              }`}>
                {s < step ? <CheckCircle2 className="w-3.5 h-3.5" /> : s}
              </div>
              <span className={`text-[10px] font-medium ${s <= step ? 'text-primary-800' : 'text-primary-400'}`}>
                {s === 1 ? 'Profile' : s === 2 ? 'Login' : 'Apply'}
              </span>
              {s < 3 && <div className={`flex-1 h-0.5 rounded ${s < step ? 'bg-emerald-400' : 'bg-gray-200'}`} />}
            </div>
          ))}
        </div>

        {/* ===== SOURCE BADGE ===== */}
        {lockedSource && (
          <div className="mx-5 mt-3 flex items-center justify-between p-2.5 bg-accent/5 border border-accent/20 rounded-xl">
            <div className="flex items-center gap-2">
              <Lock className="w-3.5 h-3.5 text-accent" />
              <span className="text-xs font-bold text-accent capitalize">{sourceConfig?.name || lockedSource}</span>
            </div>
            <div className="flex items-center gap-3 text-[10px] text-primary-500">
              <span><b className="text-accent">{selectedIds.size}</b> selected</span>
              <span>max <b>{maxBatch}</b>/batch</span>
            </div>
          </div>
        )}

        {/* ===== STEP 1: PROFILE ===== */}
        <div className="mx-5 mt-3">
          <button
            onClick={() => setShowProfileForm(!showProfileForm)}
            className="w-full flex items-center justify-between p-3 rounded-xl border border-surface-border bg-surface-muted hover:bg-surface-light transition-all"
          >
            <div className="flex items-center gap-2">
              <User className="w-4 h-4 text-primary-500" />
              <span className="text-xs font-bold text-primary-800">Your Profile</span>
            </div>
            {profileSaved && !hasRequiredProfileEmpty ? (
              <div className="flex items-center gap-1">
                <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500" />
                <span className="text-[10px] font-bold text-emerald-600">
                  {profileData.full_name || 'Saved'}
                </span>
                <ChevronDown className="w-3.5 h-3.5 text-primary-400" />
              </div>
            ) : (
              <span className="text-[10px] font-bold text-amber-600">Fill required fields</span>
            )}
          </button>

          {showProfileForm && (
            <div className="mt-2 p-4 bg-surface-muted rounded-xl border border-surface-border animate-fade-in">
              {portalFields.map((field) => (
                <div key={field.key} className="mb-2.5">
                  <label className="text-[10px] font-semibold text-primary-600 uppercase mb-0.5 flex items-center gap-1">
                    {field.icon && FIELD_ICONS[field.icon]}
                    {field.label}
                    {field.required && <span className="text-red-500">*</span>}
                  </label>
                  <input
                    type={field.type}
                    placeholder={field.placeholder}
                    value={profileData[field.key] || ''}
                    onChange={(e) => setProfileData({ ...profileData, [field.key]: e.target.value })}
                    className="input-field text-sm"
                  />
                </div>
              ))}
              <button
                onClick={handleSaveProfile}
                className="w-full py-2.5 bg-accent text-white rounded-xl text-xs font-semibold active:scale-[0.98] transition-transform"
              >
                Save Profile
              </button>
            </div>
          )}
        </div>

        {/* ===== STEP 2: LOGIN ===== */}
        {credReq && (
          <div className="mx-5 mt-3">
            {isLoggedIn ? (
              /* LOGGED IN STATE */
              <div className="p-3 bg-emerald-50 border border-emerald-200 rounded-xl">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <CheckCircle2 className="w-4 h-4 text-emerald-600" />
                    <div>
                      <p className="text-xs font-bold text-emerald-700">
                        Logged in{loginState.username ? ` as ${loginState.username}` : ''}
                      </p>
                      <p className="text-[10px] text-emerald-600">
                        Applications will be auto-submitted. No manual action needed.
                      </p>
                    </div>
                  </div>
                  <button
                    onClick={handleLogout}
                    className="text-[10px] text-primary-400 underline"
                  >
                    logout
                  </button>
                </div>
              </div>
            ) : (
              /* NOT LOGGED IN */
              <>
                <button
                  onClick={() => setShowLoginForm(!showLoginForm)}
                  className={`w-full flex items-center justify-between p-3 rounded-xl border transition-all ${
                    showLoginForm
                      ? 'border-accent bg-accent/5'
                      : 'border-amber-200 bg-amber-50 hover:bg-amber-100'
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <LogIn className="w-4 h-4 text-amber-600" />
                    <span className="text-xs font-bold text-amber-700">Login to {sourceConfig?.name || 'Portal'}</span>
                  </div>
                  <span className="text-[10px] font-bold text-amber-600">Required for auto-apply</span>
                </button>

                {showLoginForm && (
                  <div className="mt-2 p-4 bg-surface-muted rounded-xl border border-surface-border animate-fade-in">
                    <p className="text-[10px] text-primary-500 mb-3">
                      {isInternshala
                        ? 'Login once — session lasts for weeks. Your applications will be submitted automatically.'
                        : credReq.notes}
                    </p>

                    {/* Email */}
                    <div className="mb-2.5">
                      <label className="text-[10px] font-semibold text-primary-600 uppercase mb-0.5 block">
                        Email <span className="text-red-500">*</span>
                      </label>
                      <input
                        type="email"
                        placeholder="your@email.com"
                        value={credData.email || profileData.email || ''}
                        onChange={(e) => setCredData({ ...credData, email: e.target.value })}
                        className="input-field text-sm"
                      />
                    </div>

                    {/* Password */}
                    <div className="mb-2.5">
                      <label className="text-[10px] font-semibold text-primary-600 uppercase mb-0.5 block">
                        Password <span className="text-red-500">*</span>
                      </label>
                      <div className="relative">
                        <input
                          type={showPasswords.password ? 'text' : 'password'}
                          placeholder="Your portal password"
                          value={credData.password || ''}
                          onChange={(e) => setCredData({ ...credData, password: e.target.value })}
                          className="input-field text-sm pr-10"
                        />
                        <button
                          onClick={() => setShowPasswords({ ...showPasswords, password: !showPasswords.password })}
                          className="absolute right-3 top-1/2 -translate-y-1/2 text-primary-400"
                        >
                          {showPasswords.password ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                        </button>
                      </div>
                    </div>

                    {/* Captcha API Key (collapsible) */}
                    {isInternshala && (
                      <div className="mb-2.5">
                        <label className="text-[10px] font-semibold text-primary-600 uppercase mb-0.5 block">
                          Captcha API Key <span className="text-primary-400">(optional)</span>
                        </label>
                        <div className="relative">
                          <input
                            type={showPasswords.captcha ? 'text' : 'password'}
                            placeholder="CAP-xxx from capsolver.com (~$3/1000)"
                            value={credData.captcha_api_key || ''}
                            onChange={(e) => setCredData({ ...credData, captcha_api_key: e.target.value })}
                            className="input-field text-sm pr-10"
                          />
                          <button
                            onClick={() => setShowPasswords({ ...showPasswords, captcha: !showPasswords.captcha })}
                            className="absolute right-3 top-1/2 -translate-y-1/2 text-primary-400"
                          >
                            {showPasswords.captcha ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                          </button>
                        </div>
                        <p className="text-[9px] text-primary-400 mt-0.5">
                          Enables fully automated login. Without it, try login anyway or use session cookie below.
                        </p>
                      </div>
                    )}

                    {/* Login Button */}
                    <button
                      onClick={handleLogin}
                      disabled={isLoggingIn || !credData.password?.trim()}
                      className="w-full py-2.5 bg-[#0a0a0a] text-white rounded-xl text-xs font-semibold active:scale-[0.98] transition-transform flex items-center justify-center gap-2 disabled:opacity-50 mb-2"
                    >
                      {isLoggingIn ? (
                        <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Logging in...</>
                      ) : (
                        <><LogIn className="w-3.5 h-3.5" /> Login to {sourceConfig?.name || 'Portal'}</>
                      )}
                    </button>

                    {/* Advanced: Session Cookie */}
                    {isInternshala && (
                      <>
                        <button
                          onClick={() => setShowAdvanced(!showAdvanced)}
                          className="w-full flex items-center justify-center gap-1 text-[10px] text-primary-400 py-1"
                        >
                          {showAdvanced ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                          {showAdvanced ? 'Hide' : 'Show'} advanced (session cookie)
                        </button>
                        {showAdvanced && (
                          <div className="mt-2 p-3 bg-blue-50 rounded-lg border border-blue-200">
                            <p className="text-[10px] text-blue-700 mb-2">
                              If login fails, paste your session cookie from browser DevTools:
                            </p>
                            <ol className="text-[9px] text-blue-600 space-y-0.5 ml-3 list-decimal mb-2">
                              <li>Log in to <a href="https://internshala.com/login" target="_blank" rel="noopener" className="underline font-bold">internshala.com</a></li>
                              <li>Press <kbd className="bg-blue-100 px-0.5 rounded font-mono">F12</kbd> → Console → type <code className="bg-blue-100 px-0.5 rounded font-mono">document.cookie</code></li>
                              <li>Copy the output and paste below</li>
                            </ol>
                            <textarea
                              placeholder="Paste cookie string here..."
                              value={credData.session_cookie || ''}
                              onChange={(e) => setCredData({ ...credData, session_cookie: e.target.value })}
                              rows={2}
                              className="input-field text-[11px] resize-none mb-2"
                            />
                            <button
                              onClick={handleValidateCookie}
                              disabled={isLoggingIn || !credData.session_cookie?.trim()}
                              className="w-full py-2 bg-blue-600 text-white rounded-lg text-[11px] font-semibold active:scale-[0.98] disabled:opacity-50 flex items-center justify-center gap-1"
                            >
                              {isLoggingIn ? (
                                <><Loader2 className="w-3 h-3 animate-spin" /> Validating...</>
                              ) : (
                                <><RefreshCcw className="w-3 h-3" /> Validate Cookie</>
                              )}
                            </button>
                          </div>
                        )}
                      </>
                    )}
                  </div>
                )}

                {!showLoginForm && (
                  <p className="text-[10px] text-amber-600 mt-1.5 mx-1">
                    Without login, PRISM generates AI cover letters but you apply manually via links.
                  </p>
                )}
              </>
            )}
          </div>
        )}

        {/* ===== SELECTED JOBS ===== */}
        <div className="mx-5 mt-3">
          <p className="text-[10px] font-bold text-primary-500 uppercase mb-1.5">
            Selected ({selectedIds.size})
          </p>
          <div className="space-y-1.5 max-h-[200px] overflow-y-auto">
            {selectedInternships.slice(0, 10).map((item, idx) => (
              <div key={item.id} className="flex items-center gap-2.5 p-2 bg-surface-muted rounded-lg">
                <span className="w-5 h-5 bg-accent rounded-md flex items-center justify-center text-white text-[10px] font-bold flex-shrink-0">
                  {idx + 1}
                </span>
                <div className="flex-1 min-w-0">
                  <p className="text-[11px] font-semibold text-primary-800 line-clamp-1">{item.title}</p>
                  <p className="text-[10px] text-primary-500 line-clamp-1">{item.company}</p>
                </div>
                <span className="text-[11px] font-bold text-stipend-high whitespace-nowrap flex-shrink-0">
                  {item.stipend > 0 ? `${(item.stipend/1000).toFixed(0)}K` : ''}
                </span>
              </div>
            ))}
            {selectedInternships.length > 10 && (
              <p className="text-[10px] text-primary-400 text-center">
                +{selectedInternships.length - 10} more
              </p>
            )}
          </div>
        </div>

        {/* ===== BATCH PROGRESS ===== */}
        {batch.status === 'running' && (
          <div className="mx-5 mt-3 p-3 bg-accent/5 rounded-xl border border-accent/20">
            <div className="flex items-center gap-2 mb-2">
              <div className="w-4 h-4 text-accent animate-smooth-spin" style={{borderRadius:'50%', border:'2px solid currentColor', borderTopColor:'transparent'}} />
              <span className="text-xs font-bold text-accent">Applying...</span>
              <span className="text-xs text-primary-500 ml-auto">
                {batch.currentIndex + 1} / {batch.totalCount}
              </span>
            </div>
            <div className="w-full h-2 bg-primary-100 rounded-full overflow-hidden">
              <div
                className="h-full rounded-full"
                style={{
                  width: `${progress}%`,
                  transition: 'width 0.5s ease',
                  background: 'linear-gradient(90deg, #6366f1, #8b5cf6)',
                }}
              />
            </div>
            <div className="flex justify-between mt-1.5 text-[10px] text-primary-500">
              <span className="text-emerald-600 font-medium">{batch.successCount} auto-applied</span>
              <span className="text-amber-500 font-medium">{(batch as any).manualNeededCount || 0} manual</span>
              <span className="text-red-500 font-medium">{batch.failCount} failed</span>
            </div>
          </div>
        )}

        {/* ===== COOLDOWN TIMER ===== */}
        {batch.status === 'cooldown' && !isComplete && (
          <div className="mx-5 mt-3 p-3 bg-amber-50 rounded-xl border border-amber-200">
            <div className="flex items-center gap-2">
              <Clock className="w-4 h-4 text-amber-500" />
              <span className="text-xs font-bold text-amber-600">Cooldown: {remaining}</span>
            </div>
          </div>
        )}

        {/* ===== BATCH COMPLETE ===== */}
        {batch.status === 'cooldown' && isComplete && (
          <div className="mx-5 mt-3 space-y-2">
            {/* Summary */}
            <div className={`p-3 rounded-xl border ${
              batch.successCount > 0 ? 'bg-emerald-50 border-emerald-200' : 'bg-amber-50 border-amber-200'
            }`}>
              <div className="grid grid-cols-3 gap-2 text-center">
                <div>
                  <p className="text-lg font-bold text-emerald-600">{batch.successCount}</p>
                  <p className="text-[10px] text-primary-500">Auto-Applied</p>
                </div>
                <div>
                  <p className="text-lg font-bold text-amber-500">{((batch as any).assistedApplyLinks || []).length || 0}</p>
                  <p className="text-[10px] text-primary-500">Manual Needed</p>
                </div>
                <div>
                  <p className="text-lg font-bold text-red-500">{batch.failCount}</p>
                  <p className="text-[10px] text-primary-500">Failed</p>
                </div>
              </div>
            </div>

            {/* All auto-applied success */}
            {batch.successCount > 0 && ((batch as any).manualNeededCount || 0) === 0 && batch.failCount === 0 && (
              <div className="p-3 bg-emerald-50 rounded-xl border border-emerald-200">
                <div className="flex items-center gap-2 mb-1">
                  <Sparkles className="w-4 h-4 text-emerald-600" />
                  <span className="text-xs font-bold text-emerald-700">All Applied Automatically!</span>
                </div>
                <p className="text-[10px] text-emerald-600">
                  {batch.successCount} application{batch.successCount > 1 ? 's were' : ' was'} submitted. No manual action needed.
                </p>
              </div>
            )}

            {/* Assisted links (with cover letters) */}
            {((batch as any).assistedApplyLinks || []).length > 0 && (
              <div className="p-3 bg-amber-50 rounded-xl border border-amber-200">
                <div className="flex items-center gap-2 mb-2">
                  <FileText className="w-4 h-4 text-amber-600" />
                  <span className="text-xs font-bold text-amber-700">
                    Cover Letters Ready ({((batch as any).assistedApplyLinks || []).length})
                  </span>
                </div>
                <p className="text-[10px] text-amber-600 mb-2">
                  Click each link, paste the cover letter, and submit on the portal.
                  {!isLoggedIn && isInternshala && ' Login above to enable auto-submit next time.'}
                </p>
                <div className="space-y-2 max-h-[250px] overflow-y-auto">
                  {((batch as any).assistedApplyLinks || []).map((link: any, idx: number) => (
                    <div key={link.id || idx} className="bg-white rounded-lg border border-emerald-100 overflow-hidden">
                      <a
                        href={link.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="flex items-center gap-2 p-2 hover:bg-emerald-50 transition-all active:scale-[0.98]"
                        onClick={() => hapticFeedback('light')}
                      >
                        <span className="w-5 h-5 bg-emerald-600 rounded-md flex items-center justify-center text-white text-[10px] font-bold flex-shrink-0">
                          {idx + 1}
                        </span>
                        <div className="flex-1 min-w-0">
                          <p className="text-[11px] font-semibold text-primary-800 line-clamp-1">{link.title}</p>
                          {link.company && <p className="text-[10px] text-primary-500">{link.company}</p>}
                        </div>
                        <ExternalLink className="w-3.5 h-3.5 text-emerald-500 flex-shrink-0" />
                      </a>
                      {link.coverLetter && (
                        <div className="px-2 pb-2">
                          <div className="flex items-center justify-between mb-0.5">
                            <span className="text-[9px] font-bold text-emerald-600 uppercase">Cover Letter</span>
                            <button
                              onClick={() => {
                                navigator.clipboard.writeText(link.coverLetter);
                                hapticNotification('success');
                                toast.success('Copied!', { duration: 1000 });
                              }}
                              className="text-[10px] font-bold text-emerald-600 bg-emerald-100 px-1.5 py-0.5 rounded active:scale-95"
                            >
                              <Copy className="w-3 h-3 inline" /> Copy
                            </button>
                          </div>
                          <div className="text-[10px] text-primary-600 bg-emerald-50 p-1.5 rounded max-h-[80px] overflow-y-auto whitespace-pre-wrap leading-relaxed">
                            {link.coverLetter.slice(0, 400)}{link.coverLetter.length > 400 ? '...' : ''}
                          </div>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Manual links */}
            {((batch as any).manualApplyLinks || []).filter((l: any) =>
              !((batch as any).assistedApplyLinks || []).some((a: any) => a.id === l.id)
            ).length > 0 && (
              <div className="p-3 bg-blue-50 rounded-xl border border-blue-200">
                <div className="flex items-center gap-2 mb-2">
                  <ExternalLink className="w-4 h-4 text-blue-600" />
                  <span className="text-xs font-bold text-blue-700">Apply Manually</span>
                </div>
                <div className="space-y-1.5 max-h-[150px] overflow-y-auto">
                  {((batch as any).manualApplyLinks || []).filter((l: any) =>
                    !((batch as any).assistedApplyLinks || []).some((a: any) => a.id === l.id)
                  ).map((link: any, idx: number) => (
                    <a
                      key={link.id || idx}
                      href={link.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="flex items-center gap-2 p-2 bg-white rounded-lg border border-blue-100 hover:bg-blue-50 transition-all active:scale-[0.98]"
                      onClick={() => hapticFeedback('light')}
                    >
                      <span className="w-5 h-5 bg-blue-600 rounded-md flex items-center justify-center text-white text-[10px] font-bold flex-shrink-0">
                        {idx + 1}
                      </span>
                      <div className="flex-1 min-w-0">
                        <p className="text-[11px] font-semibold text-primary-800 line-clamp-1">{link.title}</p>
                        {link.company && <p className="text-[10px] text-primary-500">{link.company}</p>}
                      </div>
                      <ExternalLink className="w-3.5 h-3.5 text-blue-500 flex-shrink-0" />
                    </a>
                  ))}
                </div>
              </div>
            )}

            {/* Error details */}
            {batch.errors && batch.errors.length > 0 && (
              <div className="p-3 bg-red-50 rounded-xl border border-red-200">
                <div className="flex items-center gap-2 mb-1">
                  <AlertTriangle className="w-3.5 h-3.5 text-red-500" />
                  <span className="text-[11px] font-bold text-red-700">Errors</span>
                </div>
                <div className="space-y-1 max-h-[80px] overflow-y-auto">
                  {batch.errors.map((err, idx) => (
                    <p key={idx} className="text-[10px] text-red-600">{err.error || 'Unknown error'}</p>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* ===== ACTION BUTTON ===== */}
      <div
        className="flex-shrink-0 p-4 bg-white border-t border-surface-border"
        style={{ paddingBottom: 'calc(1rem + env(safe-area-inset-bottom, 0px))' }}
      >
        {batch.status === 'running' ? (
          <button
            onClick={() => { useAppStore.getState().cancelBatch(); hapticFeedback('medium'); }}
            className="w-full py-3.5 bg-red-600 text-white rounded-xl font-semibold text-sm flex items-center justify-center gap-2 active:scale-[0.98] transition-transform"
          >
            <Pause className="w-4 h-4" /> Pause
          </button>
        ) : batch.status === 'cooldown' && !isComplete ? (
          <button
            disabled
            className="w-full py-3.5 bg-gray-200 text-gray-500 rounded-xl font-semibold text-sm cursor-not-allowed flex items-center justify-center gap-2"
          >
            <Lock className="w-4 h-4" /> Cooldown {remaining}
          </button>
        ) : (
          <button
            onClick={handleStartApply}
            disabled={selectedIds.size === 0}
            className={`w-full py-3.5 rounded-xl font-semibold text-sm flex items-center justify-center gap-2 transition-all active:scale-[0.98] ${
              selectedIds.size > 0
                ? 'bg-[#0a0a0a] text-white shadow-lg hover:shadow-xl'
                : 'bg-gray-200 text-gray-500 cursor-not-allowed'
            }`}
          >
            {step === 1 ? (
              <><User className="w-4 h-4" /> Fill Profile & Apply</>
            ) : step === 2 && !isLoggedIn ? (
              <><Send className="w-4 h-4" /> Apply to {applyCount} (assisted mode)</>
            ) : (
              <><Zap className="w-4 h-4" /> Auto-Apply to {applyCount} {applyCount === 1 ? 'Job' : 'Jobs'}</>
            )}
          </button>
        )}

        {selectedIds.size > 0 && batch.status === 'idle' && (
          <p className="text-[10px] text-primary-400 text-center mt-1.5">
            {isLoggedIn
              ? 'PRISM will auto-submit all applications. Zero manual work.'
              : 'Login above for full automation, or apply in assisted mode now.'}
          </p>
        )}
      </div>
    </BatchPanelWrapper>
  );
}

// ===== WRAPPER =====
function BatchPanelWrapper({ isOpen, onClose, children }: { isOpen: boolean; onClose: () => void; children: React.ReactNode }) {
  const [visible, setVisible] = React.useState(false);

  React.useEffect(() => {
    if (isOpen) {
      requestAnimationFrame(() => setVisible(true));
      document.body.style.overflow = 'hidden';
    } else {
      setVisible(false);
      document.body.style.overflow = '';
    }
    return () => { document.body.style.overflow = ''; };
  }, [isOpen]);

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50"
      style={{
        backgroundColor: visible ? 'rgba(0,0,0,0.3)' : 'rgba(0,0,0,0)',
        transition: 'background-color 0.25s ease',
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div
        style={{
          position: 'absolute',
          bottom: 0, left: 0, right: 0,
          maxHeight: '90vh',
          background: '#ffffff',
          borderRadius: '24px 24px 0 0',
          boxShadow: '0 -8px 40px rgba(0,0,0,0.08)',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
          transform: visible ? 'translateY(0)' : 'translateY(100%)',
          transition: 'transform 0.3s cubic-bezier(0.22, 1, 0.36, 1)',
          willChange: 'transform',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {children}
      </div>
    </div>
  );
}
