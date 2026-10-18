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
// BACKEND USERNAME
// =========================================================
//
// Email addresses map deterministically to the backend username created
// at registration. Login also accepts legacy accounts that used a username
// directly, preserving its case as usernames are case-sensitive.
// =========================================================

const toBackendUsername = (email) => {
  // Collision-safe: "@" -> "_at_", "+" -> "_plus_", "." preserved.
  // "a.b@gmail.com" and "ab@gmail.com" now map to distinct usernames.
  const cleaned = normalizeEmail(email)
    .replace(/@/g, "_at_")
    .replace(/\+/g, "_plus_")
    .replace(/[^a-z0-9_.-]/g, "");

  return cleaned.length >= 3 ? cleaned : `user_${cleaned}`;
};

const toBackendLoginUsername = (identity) => {
  const value = String(identity || "").trim();
  return value.includes("@") ? toBackendUsername(value) : value;
};

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
      ? { user_id: stored.user_id }
      : null;
  } catch (error) {
    console.error("Could not read ARIA auth session:", error);
    return null;
  }
};

export const setAuthSession = (token, username, email, userId) => {
  // token ignored: session lives in the httpOnly cookie. Keep display details
  // in memory only, and persist only a non-PII id for per-user chat scoping.
  void token;
  currentAuthUser = {
    user_id: Number.isInteger(userId) ? userId : null,
    username: username || "",
    email: email || username || "",
  };
  clearLegacyAuthStorage();
  storage.set(KEYS.authUser, currentAuthUser.user_id
    ? { user_id: currentAuthUser.user_id }
    : null);
};

export const clearAuthSession = () => {
  currentAuthUser = null;
  clearLegacyAuthStorage();
  storage.remove(KEYS.authUser);
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
      username: toBackendUsername(currentEmail),

      password,
    });

    const username = data?.username || toBackendUsername(currentEmail);

    setAuthSession(data?.token, username, currentEmail, data?.user_id);

    return {
      success: true,

      user: {
        id: username,

        email: currentEmail,
      },
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
  const loginIdentity = String(identity || "").trim();
  const backendUsername = toBackendLoginUsername(loginIdentity);
  const displayEmail = loginIdentity.includes("@")
    ? normalizeEmail(loginIdentity)
    : "";

  try {
    const data = await authRequest("/auth/login", {
      username: backendUsername,
      password,
    });

    const username = data?.username || backendUsername;
    setAuthSession(data?.token, username, displayEmail, data?.user_id);

    return {
      success: true,
      user: { id: username, email: displayEmail },
    };
  } catch (error) {
    console.error("Login error:", error);

    // The API intentionally returns the same 401 for unknown usernames and
    // wrong passwords. Do not treat it as a signal to switch to registration.
    return {
      success: false,
      message: error?.message || "Invalid username or password.",
    };
  }
};
