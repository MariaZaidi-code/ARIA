// =========================================================
// ARIA VERSIONED STORAGE HELPER
// =========================================================
//
// Single namespaced localStorage layer. All keys live under the
// `aria.v1.*` namespace so future migrations can bump the version
// without colliding with legacy unversioned keys (which are still
// read once and migrated forward).
//
// Features: JSON-safe get/set, per-key TTL expiry, quota try/catch
// (QuotaExceededError -> evict expired entries once, then retry),
// and in-memory fallback when storage is unavailable (private mode).

const NS = "aria.v1.";

export const KEYS = {
  theme: `${NS}theme`, // "dark" | "light"
  llmMode: `${NS}ui.llm_mode`,
  ui: `${NS}ui`, // generic UI prefs object
  avatar: `${NS}profile.avatar`,
  authUser: `${NS}auth.user`,
  copilotChats: `${NS}copilot.chats`, // base; per-user suffix appended
  forecastContext: `${NS}forecast.context`,
  analysisContext: `${NS}analysis.context`,
  sharedContext: `${NS}shared.context`,
  history: `${NS}history.sessions`,
  dashboardDrill: `${NS}dashboard.drill`,
  sidebarCollapsed: `${NS}ui.sidebar_collapsed`,
  // RL feedback popup: timestamp of the last interaction, stored with a TTL
  // so the popup's shared cooldown expires without any bookkeeping.
  feedbackPopup: `${NS}ui.feedback_popup`,
};

// Legacy (unversioned) keys still honored as read-fallbacks.
const LEGACY_FALLBACK = {
  [KEYS.theme]: ["aria_theme"],
  [KEYS.llmMode]: ["aria_llm_mode"],
  [KEYS.avatar]: ["aria_avatar"],
  [KEYS.forecastContext]: ["aria_forecast_context"],
  [KEYS.analysisContext]: ["aria_analysis_context"],
  [KEYS.history]: ["aria_analysis_history"],
  [KEYS.sidebarCollapsed]: ["aria_sidebar_collapsed"],
};

const memory = new Map();

const canUseStorage = () => {
  try {
    return typeof localStorage !== "undefined";
  } catch {
    return false;
  }
};

const isQuotaError = (e) =>
  e?.name === "QuotaExceededError" ||
  e?.code === 22 ||
  e?.code === 1014 ||
  String(e?.message || "").toLowerCase().includes("quota");

const readRaw = (key) => {
  if (!canUseStorage()) return memory.has(key) ? memory.get(key) : null;
  try {
    const v = localStorage.getItem(key);
    if (v !== null) return v;
  } catch {
    return memory.has(key) ? memory.get(key) : null;
  }
  // Legacy fallback (migrate forward on next set).
  const legacyKeys = LEGACY_FALLBACK[key] || [];
  for (const lk of legacyKeys) {
    try {
      const v = localStorage.getItem(lk);
      if (v !== null) return v;
    } catch {
      /* ignore */
    }
  }
  return null;
};

/** Parse the `{ v, exp }` envelope; returns { hit, value, expired }. */
const parseEnvelope = (raw) => {
  if (raw === null || raw === undefined) return { hit: false };
  try {
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === "object" && "__aria_v1" in parsed) {
      if (parsed.exp && Date.now() > parsed.exp) return { hit: false, expired: true };
      return { hit: true, value: parsed.v };
    }
    // Unenveloped legacy value (plain string or JSON).
    try {
      return { hit: true, value: JSON.parse(raw) };
    } catch {
      return { hit: true, value: raw };
    }
  } catch {
    return { hit: true, value: raw };
  }
};

export const storage = {
  /**
   * @param {string} key
   * @param {any} [fallback]
   * @param {{ ttlMs?: number | null }} [opts]
   * @returns {any}
   */
  get(key, fallback = null, { ttlMs = null } = {}) {
    const raw = readRaw(key);
    const parsed = parseEnvelope(raw);
    if (parsed.expired) {
      try {
        storage.remove(key);
      } catch {
        /* ignore */
      }
      return fallback;
    }
    if (!parsed.hit) return fallback;
    void ttlMs;
    return parsed.value === undefined ? fallback : parsed.value;
  },

  /**
   * @param {string} key
   * @param {any} [fallback]
   * @returns {string | null}
   */
  getString(key, fallback = null) {
    const v = storage.get(key, fallback);
    if (v === null || v === undefined) return fallback;
    return typeof v === "string" ? v : String(v);
  },

  /**
   * @param {string} key
   * @param {any} value
   * @param {{ ttlMs?: number | null }} [opts]
   * @returns {boolean}
   */
  set(key, value, { ttlMs = null } = {}) {
    const envelope = JSON.stringify({
      __aria_v1: 1,
      exp: ttlMs ? Date.now() + ttlMs : 0,
      v: value,
    });
    const write = () => {
      if (!canUseStorage()) {
        memory.set(key, envelope);
        return true;
      }
      try {
        localStorage.setItem(key, envelope);
        return true;
      } catch (e) {
        if (isQuotaError(e)) {
          // Evict expired versioned keys once, then retry.
          try {
            const doomed = [];
            for (let i = 0; i < localStorage.length; i++) {
              const k = localStorage.key(i);
              if (k && k.startsWith(NS)) doomed.push(k);
            }
            for (const k of doomed) {
              try {
                const p = JSON.parse(localStorage.getItem(k) || "null");
                if (p && p.exp && Date.now() > p.exp) localStorage.removeItem(k);
              } catch {
                /* keep */
              }
            }
            localStorage.setItem(key, envelope);
            return true;
          } catch {
            memory.set(key, envelope);
            return false;
          }
        }
        memory.set(key, envelope);
        return false;
      }
    };
    return write();
  },

  /** @param {string} key */
  remove(key) {
    memory.delete(key);
    if (!canUseStorage()) return;
    try {
      localStorage.removeItem(key);
    } catch {
      /* ignore */
    }
  },

  /** Per-user key suffix (copilot chats are isolated per identity). */
  /**
   * @param {string} base
   * @param {{ username?: string, email?: string } | null} [user]
   * @returns {string}
   */
  scoped(base, user) {
    const id = user?.user_id || user?.username || user?.email || "anon";
    return `${base}.${id}`;
  },
};

/** @param {string} key @param {any} [fallback] @returns {any} */
export const getStored = (key, fallback) => storage.get(key, fallback);
/** @param {string} key @param {any} value @returns {boolean} */
export const setStored = (key, value, opts) => storage.set(key, value, opts);
/** @param {string} key */
export const removeStored = (key) => storage.remove(key);

// ---------------------------------------------------------------------------
// Drop-in Web Storage replacements (localStore / sessionStore).
//
// Same getItem / setItem / removeItem shape as localStorage/sessionStorage,
// so a page and the page that reads its handoff switch together with no
// behaviour change, but every value now lives under the versioned
// `aria.v1.raw.*` namespace inside the `{ v, exp }` envelope. Legacy
// unversioned keys are read once, moved forward, and deleted. Values stay
// strings (callers keep their own JSON.stringify / JSON.parse). Falls back
// to memory when the browser blocks storage (private mode, quota).
// ---------------------------------------------------------------------------

function makeRawStore(getArea) {
  const mem = new Map();
  const area = () => {
    try {
      return getArea() || null;
    } catch {
      return null;
    }
  };
  const nsKey = (key) => {
    const k = String(key);
    return k.startsWith(NS) ? k : `${NS}raw.${k}`;
  };
  const unwrap = (stored) => {
    try {
      const p = JSON.parse(stored);
      if (p && typeof p === "object" && !Array.isArray(p) && p.__aria_v1 === 1 && "v" in p) {
        if (p.exp && Date.now() > p.exp) return { expired: true, value: null };
        return { expired: false, value: typeof p.v === "string" ? p.v : JSON.stringify(p.v) };
      }
    } catch {
      /* not an envelope */
    }
    return { expired: false, value: stored };
  };
  const store = {
    getItem(key) {
      const a = area();
      const nk = nsKey(key);
      try {
        const stored = (a ? a.getItem(nk) : null) ?? mem.get(nk) ?? null;
        if (stored !== null && stored !== undefined) {
          const { expired, value } = unwrap(stored);
          if (expired) {
            store.removeItem(key);
            return null;
          }
          return value;
        }
        if (a && nk !== String(key)) {
          const legacy = a.getItem(String(key));
          if (legacy !== null) {
            store.setItem(key, legacy);
            a.removeItem(String(key));
            return legacy;
          }
        }
      } catch {
        /* storage blocked */
      }
      return null;
    },
    setItem(key, value) {
      const nk = nsKey(key);
      const envelope = JSON.stringify({ __aria_v1: 1, exp: 0, v: String(value) });
      const a = area();
      if (!a) {
        mem.set(nk, envelope);
        return;
      }
      try {
        a.setItem(nk, envelope);
      } catch {
        // Quota or blocked storage: keep the value for this page session.
        mem.set(nk, envelope);
      }
    },
    removeItem(key) {
      const a = area();
      mem.delete(nsKey(key));
      try {
        a?.removeItem(nsKey(key));
        a?.removeItem(String(key));
      } catch {
        /* storage blocked */
      }
    },
  };
  return store;
}

export const localStore = makeRawStore(() => (canUseStorage() ? localStorage : null));
export const sessionStore = makeRawStore(() =>
  typeof sessionStorage !== "undefined" ? sessionStorage : null,
);
