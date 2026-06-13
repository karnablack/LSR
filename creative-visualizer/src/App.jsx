import { useState, useEffect, useRef, useCallback } from 'react';
import './App.css';
import Logo from './components/Logo';
import interstellarAudio from './assets/interstellar.mp3';
import cryingCatImg from './assets/crying-cat.jpg';

// Backend URL. Defaults to local dev; override at build time with VITE_API_BASE
// (e.g. VITE_API_BASE=https://lsr.example.com) for remote / production deploys.
const API_BASE = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000';

function App() {
  // ---- Core incident state (polled from backend) --------------------------
  const [incidentActive, setIncidentActive] = useState(false);
  const [incidentData, setIncidentData] = useState(null);
  const [auditLogs, setAuditLogs] = useState([]);
  const [criticality, setCriticality] = useState(0);

  // ---- Attention mode: opt-in audio + visual nudge on SLA breach ----------
  // Default OFF. A gentle reminder for when the engineer stepped away — never a
  // pressure tactic during focused work.
  const [attentionModeEnabled, setAttentionModeEnabled] = useState(false);
  // When (seconds of no acknowledgement) the SLA cue fires. User-configurable.
  const [attentionDelaySec, setAttentionDelaySec] = useState(30);
  const [slaTimer, setSlaTimer] = useState(0);
  const [escalationSent, setEscalationSent] = useState(false);
  const audioRef = useRef(null);
  const slaTimerRef = useRef(null);

  // ---- Custom attention media (optional, chosen by the engineer) ----------
  const [customAudioUrl, setCustomAudioUrl] = useState(null);
  const [customAudioName, setCustomAudioName] = useState('');
  const [customImageUrl, setCustomImageUrl] = useState(null);
  const [customImageName, setCustomImageName] = useState('');
  const [testingSound, setTestingSound] = useState(false);

  // ---- UI state -----------------------------------------------------------
  const [activeTab, setActiveTab] = useState('overview');
  const [chatMessages, setChatMessages] = useState([]);
  const [chatInput, setChatInput] = useState('');
  const [chatLoading, setChatLoading] = useState(false);
  const [systemConfig, setSystemConfig] = useState({});
  const [triggering, setTriggering] = useState(false);
  const [backendOnline, setBackendOnline] = useState(true);

  const audioSrc = customAudioUrl || interstellarAudio;
  const imageSrc = customImageUrl || cryingCatImg;

  // Small helper: fetch that can never hang the UI (aborts after `ms`).
  const fetchWithTimeout = (url, options = {}, ms = 6000) => {
    const ctrl = new AbortController();
    const id = setTimeout(() => ctrl.abort(), ms);
    return fetch(url, { ...options, signal: ctrl.signal }).finally(() => clearTimeout(id));
  };

  const refreshIncident = useCallback(async () => {
    try {
      const res = await fetchWithTimeout(`${API_BASE}/api/incident`, {}, 4000);
      const state = await res.json();
      setBackendOnline(true);
      if (state.active && state.data) {
        setIncidentActive(true);
        setIncidentData(state.data);
        setCriticality(state.data.blast_radius_index || 0);
        setAuditLogs(state.logs || []);
      } else {
        setIncidentActive(false);
        setIncidentData(null);
        setCriticality(0);
        setAuditLogs(state.logs || []);
      }
    } catch (err) {
      // Backend unreachable — surface it so the user knows to start it.
      setBackendOnline(false);
    }
  }, []);

  // ---- Poll incident state every 2s (background refresh) ------------------
  useEffect(() => {
    refreshIncident(); // immediate first paint, don't wait 2s
    const poll = setInterval(refreshIncident, 2000);
    return () => clearInterval(poll);
  }, [refreshIncident]);

  // ---- Load non-sensitive config ------------------------------------------
  useEffect(() => {
    (async () => {
      try {
        const res = await fetch(`${API_BASE}/api/config`);
        setSystemConfig(await res.json());
      } catch (err) {
        console.error('Error loading config:', err);
      }
    })();
  }, []);

  // ---- SLA countdown + single escalation when the chosen window is exceeded -
  useEffect(() => {
    if (incidentActive && incidentData) {
      slaTimerRef.current = setInterval(() => {
        setSlaTimer((prev) => {
          const next = prev + 1;
          // Fire once when the user-configured attention window is crossed.
          if (next >= attentionDelaySec && !escalationSent) {
            triggerEscalation();
            setEscalationSent(true);
          }
          return next;
        });
      }, 1000);
    } else {
      if (slaTimerRef.current) clearInterval(slaTimerRef.current);
      setSlaTimer(0);
      setEscalationSent(false);
      stopAudio();
    }
    return () => {
      if (slaTimerRef.current) clearInterval(slaTimerRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [incidentActive, incidentData, escalationSent, attentionDelaySec]);

  // ---- Stop the audio immediately whenever attention mode is turned off ----
  useEffect(() => {
    if (!attentionModeEnabled) {
      stopAudio();
      setTestingSound(false);
    }
  }, [attentionModeEnabled]);

  const stopAudio = () => {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.currentTime = 0;
    }
  };

  const primeAudio = () => {
    const a = audioRef.current;
    if (!a) return;
    const restore = a.muted;
    a.muted = true;
    const p = a.play();
    if (p && typeof p.then === 'function') {
      p.then(() => { a.pause(); a.currentTime = 0; a.muted = restore; })
       .catch(() => { a.muted = restore; });
    } else {
      a.muted = restore;
    }
  };

  // Fire the backend escalation (Teams/Slack follow-up). Optionally play the
  // local audio nudge if the engineer enabled attention mode.
  const triggerEscalation = async () => {
    try {
      await fetch(`${API_BASE}/api/incident/escalate`, { method: 'POST' });
    } catch (err) {
      console.error('Escalation error:', err);
    }
    if (attentionModeEnabled && audioRef.current) {
      audioRef.current.volume = 0.15;
      audioRef.current.play().catch(() => {});
      let step = 0;
      const ramp = setInterval(() => {
        if (audioRef.current && attentionModeEnabled && step < 4) {
          audioRef.current.volume = Math.min(0.15 + step * 0.12, 0.55);
          step += 1;
        } else {
          clearInterval(ramp);
        }
      }, 1500);
    }
  };

  // ---- Media pickers ------------------------------------------------------
  const onPickAudio = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (customAudioUrl) URL.revokeObjectURL(customAudioUrl);
    setCustomAudioUrl(URL.createObjectURL(file));
    setCustomAudioName(file.name);
  };
  const onPickImage = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (customImageUrl) URL.revokeObjectURL(customImageUrl);
    setCustomImageUrl(URL.createObjectURL(file));
    setCustomImageName(file.name);
  };
  const resetMedia = () => {
    if (customAudioUrl) URL.revokeObjectURL(customAudioUrl);
    if (customImageUrl) URL.revokeObjectURL(customImageUrl);
    setCustomAudioUrl(null); setCustomAudioName('');
    setCustomImageUrl(null); setCustomImageName('');
  };
  const toggleTestSound = () => {
    if (!audioRef.current) return;
    if (testingSound) {
      stopAudio();
      setTestingSound(false);
    } else {
      audioRef.current.volume = 0.4;
      audioRef.current.play().catch(() => {});
      setTestingSound(true);
    }
  };

  // ---- Demo trigger -------------------------------------------------------
  const triggerDemo = async (assetId) => {
    primeAudio(); // runs inside the click gesture → unlocks audio for later SLA cue
    setTriggering(true);
    try {
      await fetchWithTimeout(`${API_BASE}/api/demo/trigger`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ asset_id: assetId }),
      });
      setBackendOnline(true);
      await refreshIncident(); // show the incident immediately, no poll wait
    } catch (err) {
      // Most common cause: backend isn't running on :8000.
      setBackendOnline(false);
    } finally {
      setTriggering(false);
    }
  };

  // ---- Assistant chat -----------------------------------------------------
  const handleChatSubmit = async (e) => {
    e.preventDefault();
    if (!chatInput.trim()) return;
    const question = chatInput;
    setChatMessages((prev) => [...prev, { role: 'user', content: question }]);
    setChatInput('');
    setChatLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/copilot/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question }),
      });
      const data = await res.json();
      setChatMessages((prev) => [
        ...prev,
        { role: 'assistant', content: data.reply, confidence: data.confidence },
      ]);
    } catch (err) {
      setChatMessages((prev) => [
        ...prev,
        { role: 'assistant', content: `Error: ${err.message}`, error: true },
      ]);
    } finally {
      setChatLoading(false);
    }
  };

  // ---- Resolve ------------------------------------------------------------
  const handleResolve = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/incident/resolve`, { method: 'POST' });
      if (res.ok) {
        stopAudio();
        await refreshIncident(); // return to idle screen immediately
      }
    } catch (err) {
      console.error('Error resolving incident:', err);
    }
  };

  // ---- Presentation helpers ----------------------------------------------
  const statusColor = () => {
    if (!incidentActive) return '#10b981';
    if (criticality >= 0.7) return '#ff4a4a';
    if (criticality >= 0.5) return '#f97316';
    return '#eab308';
  };

  const statusText = () => {
    if (!incidentActive) return 'OPERATIONAL';
    const map = {
      AUTO_REMEDIATION: 'AUTO-REMEDIATION',
      HUMAN_VALIDATION_REQUIRED: 'AWAITING APPROVAL',
      ESCALATION_REQUIRED: 'MANUAL REVIEW',
    };
    return map[incidentData?.incident_status] || incidentData?.incident_status || 'ACTIVE';
  };

  const logClass = (line) => {
    if (/✅|✓|SUCCESS/.test(line)) return 'log-line log-success';
    if (/❌|⚠️|FAIL|WARN/.test(line)) return 'log-line log-warn';
    if (/🛡️|DECISION|FOUNDRY|FABRIC|WORK IQ/.test(line)) return 'log-line log-accent';
    return 'log-line';
  };

  const slaThreshold = attentionDelaySec;
  const slaBreached = incidentActive && slaTimer >= slaThreshold;

  const TABS = { overview: '📊 Overview', logs: '🧠 Reasoning', chat: '💬 Copilot', settings: '⚙️ Settings' };

  return (
    <div className="lsr-dashboard">
      {/* preload="none": the 5 MB clip is fetched only when actually played,
          never on page load — keeps the dashboard fast. */}
      <audio ref={audioRef} src={audioSrc} loop preload="none" onEnded={() => setTestingSound(false)} />

      {/* ===================== HEADER ===================== */}
      <header className="lsr-header">
        <div className="brand">
          <Logo size={42} status={incidentActive ? 'incident' : 'healthy'} />
          <div className="brand-text">
            <h1>LSR</h1>
            <span className="brand-sub">Synaptic Response Center</span>
          </div>
        </div>

        <div className="header-status">
          <span className="status-dot" style={{ backgroundColor: statusColor() }} />
          <div className="status-block">
            <span className="status-label">System Status</span>
            <span className="status-value" style={{ color: statusColor() }}>{statusText()}</span>
          </div>
          {incidentActive && (
            <div className="status-block sla-block">
              <span className="status-label">SLA Elapsed</span>
              <span className={`status-value ${slaBreached ? 'sla-breached' : ''}`}>
                {slaTimer}s / {slaThreshold}s
              </span>
            </div>
          )}
        </div>

        <div className="header-right">
          <span className="env-badge">{systemConfig.environment || 'dev'}</span>
          <span className={`llm-badge ${systemConfig.llm_enabled ? 'on' : 'off'}`}>
            {systemConfig.llm_enabled ? `AI: ${systemConfig.llm_provider}` : 'AI: offline'}
          </span>
        </div>
      </header>

      {/* ===================== MAIN ===================== */}
      <main className="lsr-main">
        {/* Tabs are always present — the workspace persists with or without an incident. */}
        <nav className="tabs-container">
          {Object.entries(TABS).map(([tab, label]) => (
            <button
              key={tab}
              className={`tab ${activeTab === tab ? 'active' : ''}`}
              onClick={() => setActiveTab(tab)}
            >
              {label}
            </button>
          ))}
        </nav>

        {/* ----------- OVERVIEW ----------- */}
        {activeTab === 'overview' && (
          incidentActive ? (
            <div className="tab-content overview-grid">
              <div className="incident-card">
                <div className="card-header">
                  <h3>Active Incident</h3>
                  <span className={`severity-badge sev-${incidentData?.severity || 'medium'}`}>
                    {(incidentData?.severity || 'medium').toUpperCase()}
                  </span>
                </div>
                <div className="metric-grid">
                  <div className="metric">
                    <span className="metric-label">Asset</span>
                    <span className="metric-value">{incidentData?.asset_id}</span>
                    <span className="metric-detail">{incidentData?.asset_name}</span>
                  </div>
                  <div className="metric">
                    <span className="metric-label">Business Impact</span>
                    <span className="metric-value sm">{incidentData?.impacted_business_process}</span>
                  </div>
                  <div className="metric">
                    <span className="metric-label">Criticality Index</span>
                    <span className="metric-value" style={{ color: statusColor() }}>
                      {incidentData?.blast_radius_index?.toFixed(2) || '0.00'}
                    </span>
                  </div>
                  <div className="metric">
                    <span className="metric-label">Assigned Engineer</span>
                    <span className="metric-value sm">{incidentData?.assigned_engineer}</span>
                    <span className={`metric-detail ${incidentData?.assigned_engineer_presence === 'Online' ? 'online' : 'offline'}`}>
                      {incidentData?.assigned_engineer_presence}
                    </span>
                  </div>
                </div>

                <div className="metric-full">
                  <span className="metric-label">Remediation Runbook (Foundry IQ)</span>
                  <code>{incidentData?.resolved_runbook}</code>
                </div>
                <div className="metric-full">
                  <span className="metric-label">Decision</span>
                  <span className={`posture posture-${incidentData?.incident_status?.toLowerCase().replace(/_/g, '-')}`}>
                    {statusText()}
                  </span>
                </div>

                <div className="action-buttons">
                  <button className="btn btn-success" onClick={handleResolve}>✓ Acknowledge & Resolve</button>
                </div>
              </div>

              {/* Blast-radius topology (Fabric IQ) — no financial counters */}
              <div className="topology-card">
                <h3>Blast Radius · Fabric IQ Topology</h3>
                <div className="topology-grid">
                  {(incidentData?.topology || []).map((node) => {
                    const affected = node.asset_id === incidentData?.asset_id;
                    return (
                      <div key={node.asset_id} className={`topo-node ${affected ? 'affected' : ''}`}>
                        <div className="topo-head">
                          <span className="topo-id">{node.asset_id}</span>
                          {affected && <span className="topo-flag">IMPACTED</span>}
                        </div>
                        <span className="topo-name">{node.asset_name}</span>
                        <span className="topo-proc">{node.impacted_business_process}</span>
                        <div className="topo-bar">
                          <div
                            className="topo-bar-fill"
                            style={{ width: `${Math.round((node.criticality_index || 0) * 100)}%` }}
                          />
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          ) : (
            <div className="tab-content">
              <div className="idle-card">
                <Logo size={72} status="healthy" />
                <h2>System Operational</h2>
                <p className="idle-sub">Monitoring ambient infrastructure signals — scaled to zero until an anomaly arrives.</p>
                {!backendOnline && (
                  <div className="backend-warning">
                    ⚠️ Can't reach the backend on port 8000. Start it
                    (<code>uvicorn app:app --port 8000</code>) — the buttons will work once it's up.
                  </div>
                )}
                <div className="demo-triggers">
                  <p className="demo-hint">Simulate an incident to explore the response workflow:</p>
                  <div className="demo-buttons">
                    <button className="btn btn-outline" disabled={triggering || !backendOnline} onClick={() => triggerDemo('gateway_2')}>
                      ⚡ Low-risk · Gateway congestion
                    </button>
                    <button className="btn btn-primary" disabled={triggering || !backendOnline} onClick={() => triggerDemo('db_5')}>
                      🔥 High-risk · Database outage
                    </button>
                  </div>
                </div>
              </div>
            </div>
          )
        )}

        {/* ----------- REASONING / LOGS ----------- */}
        {activeTab === 'logs' && (
          <div className="tab-content">
            <div className="logs-card">
              <h3>Agent Reasoning Stream</h3>
              <p className="logs-sub">Live trace of how the Fabric IQ, Foundry IQ and Work IQ agents cross-examine an incident.</p>
              <div className="logs-display">
                {auditLogs.length === 0 ? (
                  <p className="empty-logs">No active incident. Trigger one from the Overview tab to see the reasoning stream.</p>
                ) : (
                  auditLogs.map((log, i) => <div key={i} className={logClass(log)}>{log}</div>)
                )}
              </div>
            </div>
          </div>
        )}

        {/* ----------- COPILOT CHAT ----------- */}
        {activeTab === 'chat' && (
          <div className="tab-content">
            <div className="chat-card">
              <div className="chat-messages">
                {chatMessages.length === 0 && (
                  <div className="chat-welcome">
                    <h4>LSR Copilot</h4>
                    <p>Ask about the current incident, remediation strategy, or SLA posture. Answers are grounded on the live incident context.</p>
                  </div>
                )}
                {chatMessages.map((msg, i) => (
                  <div key={i} className={`message message-${msg.role}`}>
                    <div className="message-content">
                      {msg.content}
                      {msg.confidence !== undefined && (
                        <small className="confidence">Confidence: {(msg.confidence * 100).toFixed(0)}%</small>
                      )}
                    </div>
                  </div>
                ))}
                {chatLoading && (
                  <div className="message message-assistant">
                    <div className="typing-indicator"><span /><span /><span /></div>
                  </div>
                )}
              </div>
              <form className="chat-input-form" onSubmit={handleChatSubmit}>
                <input
                  type="text"
                  placeholder="Ask Copilot about this incident…"
                  value={chatInput}
                  onChange={(e) => setChatInput(e.target.value)}
                  disabled={chatLoading}
                />
                <button type="submit" disabled={chatLoading || !chatInput.trim()}>Send</button>
              </form>
            </div>
          </div>
        )}

        {/* ----------- SETTINGS ----------- */}
        {activeTab === 'settings' && (
          <div className="tab-content settings-grid">
            <div className="settings-card">
              <h3>Attention Nudge</h3>
              <label className="setting-item">
                <input
                  type="checkbox"
                  checked={attentionModeEnabled}
                  onChange={(e) => {
                    setAttentionModeEnabled(e.target.checked);
                    if (e.target.checked) primeAudio(); // unlock audio while opting in
                  }}
                />
                <span className="label-text">
                  <strong>Enable attention cue</strong>
                  <small>
                    Plays a soft sound + shows an image in this browser if the SLA window passes with no
                    acknowledgement. Off by default. The Teams/Slack follow-up is sent regardless.
                  </small>
                </span>
              </label>

              <div className="settings-section">
                <h4>Cue media (optional)</h4>
                <p className="section-hint">Pick your own sound and image, or keep the defaults.</p>

                <div className="media-pickers">
                  <div className="media-pick">
                    <span className="media-label">🔊 Alert sound</span>
                    <label className="file-btn">
                      Choose file…
                      <input type="file" accept="audio/*" onChange={onPickAudio} hidden />
                    </label>
                    <small className="media-name">{customAudioName || 'Default · interstellar.mp3'}</small>
                  </div>

                  <div className="media-pick">
                    <span className="media-label">🖼️ Alert image</span>
                    <label className="file-btn">
                      Choose file…
                      <input type="file" accept="image/*" onChange={onPickImage} hidden />
                    </label>
                    <small className="media-name">{customImageName || 'Default · crying-cat.jpg'}</small>
                  </div>
                </div>

                <div className="media-preview-row">
                  <img className="media-preview" src={imageSrc} alt="Attention cue preview" />
                  <div className="media-actions">
                    <button className="btn btn-outline btn-sm" onClick={toggleTestSound} disabled={!attentionModeEnabled}>
                      {testingSound ? '■ Stop test' : '▶ Test sound'}
                    </button>
                    <button className="btn btn-ghost btn-sm" onClick={resetMedia}>Reset to defaults</button>
                  </div>
                </div>
                {!attentionModeEnabled && (
                  <small className="section-hint">Enable the cue above to test the sound.</small>
                )}
              </div>

              <div className="settings-section">
                <h4>Trigger timing</h4>
                <p className="section-hint">
                  How long the incident can go unacknowledged before the sound &amp; image turn on.
                </p>
                <div className="delay-presets">
                  {[15, 30, 60, 90].map((s) => (
                    <button
                      key={s}
                      className={`chip ${attentionDelaySec === s ? 'active' : ''}`}
                      onClick={() => setAttentionDelaySec(s)}
                    >
                      {s}s
                    </button>
                  ))}
                </div>
                <label className="delay-custom">
                  Custom
                  <input
                    type="number"
                    min="5"
                    max="600"
                    value={attentionDelaySec}
                    onChange={(e) =>
                      setAttentionDelaySec(Math.max(5, Math.min(600, Number(e.target.value) || 5)))
                    }
                  />
                  <span>seconds</span>
                </label>
              </div>
            </div>

            <div className="settings-card">
              <h3>Runtime Configuration</h3>
              <ul className="config-list">
                <li><span>Environment</span><b>{systemConfig.environment || '—'}</b></li>
                <li><span>AI Provider</span><b>{systemConfig.llm_enabled ? systemConfig.llm_provider : 'offline (deterministic)'}</b></li>
                <li><span>Auto-Remediation</span><b>{systemConfig.auto_remediation_enabled ? 'Enabled' : 'Disabled'}</b></li>
                <li><span>Teams Webhook</span><b>{systemConfig.teams_webhook_configured ? 'Configured' : 'Not configured'}</b></li>
                <li><span>Slack Webhook</span><b>{systemConfig.slack_webhook_configured ? 'Configured' : 'Not configured'}</b></li>
                <li><span>SLA Window</span><b>{systemConfig.sla_breach_threshold_seconds ?? 30}s</b></li>
              </ul>
            </div>
          </div>
        )}
      </main>

      {/* ============ ATTENTION OVERLAY (opt-in) ============ */}
      {attentionModeEnabled && slaBreached && (
        <div className="attention-overlay">
          <img src={imageSrc} alt="Gentle reminder: incident awaiting acknowledgement" />
          <span>Still awaiting acknowledgement</span>
        </div>
      )}

      {/* ===================== FOOTER ===================== */}
      <footer className="lsr-footer">
        <span>LSR v1.1 · Synaptic Response Center</span>
        <span>Fabric IQ · Foundry IQ · Work IQ</span>
      </footer>
    </div>
  );
}

export default App;
