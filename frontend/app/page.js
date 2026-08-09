"use client";

import { useEffect, useRef, useState } from "react";
import styles from "./page.module.css";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function Home() {
  const [incidents, setIncidents] = useState([]);
  const [selectedIncidentId, setSelectedIncidentId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [question, setQuestion] = useState("");
  const [anthropicKey, setAnthropicKey] = useState("");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [asking, setAsking] = useState(false);
  const threadEnd = useRef(null);

  const selectedIncident = incidents.find((incident) => incident.id === selectedIncidentId) || incidents[0];

  async function loadIncidents() {
    setLoading(true);
    try {
      const res = await fetch(`${API_URL}/sre/incidents`);
      if (res.ok) {
        const data = await res.json();
        setIncidents(data);
        if (!selectedIncidentId && data.length > 0) {
          setSelectedIncidentId(data[0].id);
        }
      }
    } finally {
      setLoading(false);
    }
  }

  async function refreshIncidents() {
    setRefreshing(true);
    try {
      const res = await fetch(`${API_URL}/sre/refresh`, { method: "POST" });
      if (res.ok) {
        const data = await res.json();
        setIncidents(data);
        if (data.length > 0) {
          setSelectedIncidentId(data[0].id);
        }
      }
    } finally {
      setRefreshing(false);
    }
  }

  useEffect(() => {
    loadIncidents();
  }, []);

  useEffect(() => {
    threadEnd.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function askQuestion(e) {
    e.preventDefault();
    if (!question.trim()) return;
    const q = question;
    setQuestion("");
    setMessages((current) => [...current, { role: "user", content: q, id: `user-${Date.now()}` }]);
    setAsking(true);

    try {
      const res = await fetch(`${API_URL}/sre/diagnose`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(anthropicKey ? { "X-Anthropic-Key": anthropicKey } : {}),
        },
        body: JSON.stringify({ incident_id: selectedIncident?.id, question: q }),
      });
      if (res.ok) {
        const data = await res.json();
        setMessages((current) => [
          ...current,
          { role: "assistant", content: data.answer, id: `assistant-${Date.now()}`, citations: data.used_incidents },
        ]);
      } else {
        const errorPayload = await res.json().catch(() => ({}));
        setMessages((current) => [
          ...current,
          { role: "assistant", content: `Error: ${errorPayload.detail || res.statusText}`, id: `error-${Date.now()}` },
        ]);
      }
    } finally {
      setAsking(false);
    }
  }

  return (
    <div className={styles.shell}>
      <aside className={styles.sidebar}>
        <div className={styles.brand}>
          <h1>SRE Forge AI</h1>
          <p>Autonomous incident triage</p>
        </div>

        <div className={styles.launchSummary}>
          <div>
            <div className={styles.shelfLabel}>Open incidents</div>
            <div className={styles.launchCount}>{incidents.length}</div>
          </div>
          <button className={styles.refreshBtn} onClick={refreshIncidents} disabled={refreshing}>
            {refreshing ? "Refreshing…" : "Refresh incidents"}
          </button>
        </div>

        <div className={styles.shelf}>
          {loading ? (
            <div className={styles.empty}>Loading incident feed…</div>
          ) : incidents.length === 0 ? (
            <div className={styles.empty}>No active incidents are available.</div>
          ) : (
            incidents.map((incident) => (
              <div
                key={incident.id}
                className={`${styles.card} ${incident.id === selectedIncidentId ? styles.active : ""}`}
                onClick={() => setSelectedIncidentId(incident.id)}
              >
                <h3>{incident.title}</h3>
                <p className={styles.meta}>{incident.service}</p>
                <p className={styles.launchMeta}>{incident.severity.toUpperCase()} · {incident.status}</p>
                <p className={styles.small}>{new Date(incident.started_at).toLocaleString()}</p>
              </div>
            ))
          )}
        </div>
      </aside>

      <main className={styles.main}>
        <div className={styles.header}>
          <div>
            <h2>{selectedIncident ? selectedIncident.title : "SRE Incident Triage"}</h2>
            <div className={styles.meta}>
              {selectedIncident
                ? `${selectedIncident.service} · ${selectedIncident.status}`
                : "Select an incident to inspect."}
            </div>
          </div>
          <div className={styles.badge}>{selectedIncident?.severity?.toUpperCase() || "N/A"}</div>
        </div>

        {selectedIncident && (
          <section className={styles.launchDetails}>
            <div className={styles.detailsRow}>
              <div>
                <span className={styles.label}>Service</span>
                <p>{selectedIncident.service}</p>
              </div>
              <div>
                <span className={styles.label}>Status</span>
                <p>{selectedIncident.status}</p>
              </div>
            </div>
            <div className={styles.detailsRow}>
              <div>
                <span className={styles.label}>Severity</span>
                <p>{selectedIncident.severity}</p>
              </div>
              <div>
                <span className={styles.label}>Started</span>
                <p>{new Date(selectedIncident.started_at).toLocaleString()}</p>
              </div>
            </div>
            <div className={styles.detailDescription}>{selectedIncident.summary || "No incident summary available."}</div>
            <div className={styles.detailDescription}>
              <strong>Logs</strong>
              <pre className={styles.pre}>{selectedIncident.logs || "No logs captured."}</pre>
            </div>
            <div className={styles.detailDescription}>
              <strong>Metrics</strong>
              <pre className={styles.pre}>{selectedIncident.metrics || "No metric data available."}</pre>
            </div>
            <div className={styles.detailDescription}>
              <label className={styles.label} htmlFor="anthropic-key-input">
                Paste your Anthropic API key to use your own model credentials (not persisted)
              </label>
              <input
                id="anthropic-key-input"
                className={styles.input}
                type="password"
                placeholder="Enter Anthropic API key"
                value={anthropicKey}
                onChange={(e) => setAnthropicKey(e.target.value)}
              />
            </div>
          </section>
        )}

        <div className={styles.thread}>
          {messages.length === 0 ? (
            <div className={styles.empty}>Ask SRE Forge AI for the likely root cause, remediation steps, or how to resolve this outage.</div>
          ) : (
            messages.map((message) => (
              <div key={message.id} className={`${styles.bubbleRow} ${message.role}`}>
                <div className={`${styles.bubble} ${message.role}`}>
                  {message.content}
                  {message.citations && message.citations.length > 0 && (
                    <div className={styles.citations}>
                      {message.citations.map((incident) => (
                        <span key={incident} className={styles.citeTag}>{incident}</span>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ))
          )}
          {asking && <div className={styles.pending}>SRE Forge AI is composing your diagnosis…</div>}
          <div ref={threadEnd} />
        </div>

        <form className={styles.composer} onSubmit={askQuestion}>
          <input
            placeholder="Ask about this incident, remediation, or SRE next steps..."
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
          />
          <button type="submit" className={styles.primaryBtn} disabled={asking || !question.trim()}>
            {asking ? "Diagnosing…" : "Ask SRE Forge AI"}
          </button>
        </form>
      </main>
    </div>
  );
}
