// =========================================================
// DAY 9 - HISTORY STORAGE
// =========================================================
//
// Frontend development version.
//
// Current:
// React
//   ↓
// localStorage
//
// Later:
// React
//   ↓
// FastAPI
//   ↓
// PostgreSQL
// =========================================================

const HISTORY_STORAGE_KEY = "aria_analysis_history";

// =========================================================
// GET ALL HISTORY
// =========================================================

export const getHistorySessions = () => {
  try {
    const storedHistory = localStorage.getItem(HISTORY_STORAGE_KEY);

    if (!storedHistory) {
      return [];
    }

    const parsedHistory = JSON.parse(storedHistory);

    return Array.isArray(parsedHistory) ? parsedHistory : [];
  } catch (error) {
    console.error("Could not load ARIA history:", error);

    return [];
  }
};

// =========================================================
// SAVE ALL HISTORY
// =========================================================

const saveHistorySessions = (sessions) => {
  try {
    localStorage.setItem(HISTORY_STORAGE_KEY, JSON.stringify(sessions));

    return true;
  } catch (error) {
    console.error("Could not save ARIA history:", error);

    return false;
  }
};

// =========================================================
// ADD ONE SESSION
// =========================================================

export const addHistorySession = (session) => {
  const currentHistory = getHistorySessions();

  const updatedHistory = [session, ...currentHistory];

  saveHistorySessions(updatedHistory);

  return updatedHistory;
};

// =========================================================
// UPDATE ONE SESSION
// =========================================================

export const updateHistorySession = (sessionId, updates) => {
  const currentHistory = getHistorySessions();

  const updatedHistory = currentHistory.map((session) =>
    session.id === sessionId
      ? {
          ...session,
          ...updates,
        }
      : session,
  );

  saveHistorySessions(updatedHistory);

  return updatedHistory;
};

// =========================================================
// DELETE ONE SESSION
// =========================================================

export const deleteHistorySession = (sessionId) => {
  const currentHistory = getHistorySessions();

  const updatedHistory = currentHistory.filter(
    (session) => session.id !== sessionId,
  );

  saveHistorySessions(updatedHistory);

  return updatedHistory;
};
