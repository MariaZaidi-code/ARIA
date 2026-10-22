// =========================================================
// ARIA FRONTEND AUTH STORAGE
// =========================================================
//
// Connected to the ARIA FastAPI backend:
//
// React (this file)
//   â†“  POST /api/auth/register | /api/auth/login
// FastAPI
//   â†“
// SQLite + JWT
//
// Cookie auth: the backend sets an httpOnly `aria_token` cookie on
// login/register. No JWT or personally identifying user details are stored
// in localStorage; only the opaque backend user id scopes local chat data.

import { API_BASE } from "../services/api.js";
import { KEYS, storage } from "./storage.js";

const TOKEN_KEY = "aria_auth_token"; // legacy: kept only to clear old sessions; cookie auth now
const USER_KEY = "aria_auth_user";
let currentAuthUser = null;

const clearLegacyAuthStorage = () => {
  try {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
  } catch { /* ignore unavailable storage */ }
};

clearLegacyAuthStorage();
try {
  const storedUser = storage.get(KEYS.authUser, null);
  if (storedUser && !Number.isInteger(storedUser.user_id)) {
    storage.remove(KEYS.authUser);
  }
} catch { /* ignore unavailable storage */ }

// =========================================================
export const isTokenExpired = (token) => {
  try {
    const parts = (token || "").split(".");
    if (parts.length !== 3) return false;
    const payload = JSON.parse(atob(parts[1].replace(/-/g, "+").replace(/_/g, "/")));
    if (!payload.exp) return false;
    return Date.now() / 1000 > payload.exp;
  } catch {
    return false;
  }
};

// =========================================================
// NORMALIZE EMAIL
// =========================================================

const normalizeEmail = (email) => {
  return (email || "").trim().toLowerCase();
};

// =========================================================
// TOKEN / SESSION STORAGE
// =========================================================

// Cookie auth: the backend httpOnly `aria_token` cookie is the session.
// No JWT is kept in localStorage; getAuthToken stays as a deprecated stub
// returning "" so legacy callers never emit `Bearer null`/empty.
export const getAuthToken = () => {
  return "";
};

export const getAuthUser = () => {
  if (currentAuthUser) return currentAuthUser;
  try {
    const stored = storage.get(KEYS.authUser, null);
    return Number.isInteger(stored?.user_id)
      ? { user_id: stored.user_id, is_admin: stored.is_admin === true }
      : null;
  } catch (error) {
    console.error("Could not read ARIA auth session:", error);
    return null;
  }
};

export const setAuthSession = (token, username, email, userId, isAdmin = false) => {
  // token ignored: session lives in the httpOnly cookie. Keep display details
  // in memory; persist only the non-PII id and a non-authoritative role hint.
  // Admin API access is always checked against the server allowlist.
  void token;
  currentAuthUser = {
    user_id: Number.isInteger(userId) ? userId : null,
    username: username || "",
    email: email || username || "",
    is_admin: isAdmin === true,
  };
  clearLegacyAuthStorage();
  storage.set(KEYS.authUser, currentAuthUser.user_id
    ? { user_id: currentAuthUser.user_id, is_admin: currentAuthUser.is_admin }
    : null);
};

export const clearAuthSession = () => {
  currentAuthUser = null;
  clearLegacyAuthStorage();
  storage.remove(KEYS.authUser);
  // Drop cross-page handoff context so a previous account's analysis
  // context cannot pollute the next session in the same browser tab.
  try {
    for (const k of ["aria_shared_context", "aria_forecast_prefill", "aria_insight_handoff", "aria_hypothesis_prefill", "aria_copilot_context", "aria_explore_prefill", "aria_whatif_prefill", "aria_toast"]) {
      sessionStorage.removeItem(k);
    }
  } catch { /* ignore */ }
  try {
    for (const k of [KEYS.analysisContext, KEYS.forecastContext, KEYS.sharedContext, KEYS.dashboardDrill, "aria_analysis_context", "aria_forecast_context", "aria_dashboard_drill"]) {
      storage.remove(k);
      localStorage.removeItem(k);
    }
  } catch { /* ignore */ }
};

// =========================================================
// BACKEND AUTH REQUEST
// =========================================================

const authRequest = async (path, payload) => {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",

    // Include cookies so the backend's httpOnly `aria_token` cookie
    // (set on login/register) is stored and sent automatically.
    // The httpOnly cookie is the only persistent credential.
    credentials: "include",

    headers: {
      "Content-Type": "application/json",
    },

    body: JSON.stringify(payload),
  });

  let data;

  try {
    data = await response.json();
  } catch {
    data = {};
  }

  if (!response.ok) {
    const message =
      (typeof data?.detail === "string" && data.detail) ||
      data?.message ||
      `Request failed (${response.status}).`;

    const error = new Error(message);

    error.status = response.status;

    throw error;
  }

  return data;
};

// =========================================================
// REGISTER USER
// =========================================================

export const registerLocalUser = async (email, password) => {
  const currentEmail = normalizeEmail(email);

  try {
    const data = await authRequest("/auth/register", {
      email: currentEmail,
      password,
    });

    return {
      success: true,
      verificationRequired: true,
      email: currentEmail,
      message: data?.message || "Check your email for a verification link.",
    };
  } catch (error) {
    console.error("Registration error:", error);

    return {
      success: false,

      message: error?.message || "Could not create your account.",
    };
  }
};

// =========================================================
// LOGIN USER
// =========================================================

export const authenticateLocalUser = async (identity, password) => {
  const email = normalizeEmail(identity);

  try {
    const data = await authRequest("/auth/login", {
      email,
      password,
    });

    const username = data?.username || email;
    setAuthSession(data?.token, username, email, data?.user_id, data?.is_admin);

    return {
      success: true,
      user: { id: username, email, is_admin: data?.is_admin === true },
    };
  } catch (error) {
    console.error("Login error:", error);

    return {
      success: false,
      message: error?.message || "Invalid email or password.",
      needsVerification: error?.status === 403,
    };
  }
};

export const verifyEmailAddress = async (token) =>
  authRequest("/auth/verify-email", { token });

export const resendVerificationEmail = async (email) =>
  authRequest("/auth/resend-verification", { email: normalizeEmail(email) });
