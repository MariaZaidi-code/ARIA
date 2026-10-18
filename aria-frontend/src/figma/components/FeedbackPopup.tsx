/* Random RL feedback popup.

   Appears occasionally while the user works (probability + shared
   cooldown), asks for a 1-5 star check-in and an optional comment, and
   posts both to POST /api/rl/feedback. The backend maps the rating to a
   reward in [-1, +1] and appends a (state, action, outcome, reward)
   event for the future RL model (core/rl.py). Submission is fully
   non-blocking: a failure never interrupts the page.

   Randomness guards:
   - never in automated browsers (navigator.webdriver -> e2e/CI safe)
   - at most once per session
   - shared cooldown across sessions (storage TTL, default 72h)
   - only rolls while the tab is visible
   VITE_FEEDBACK_PROBABILITY overrides the per-roll chance (0 disables). */

import { useEffect, useRef, useState } from "react";
import { Star, X } from "lucide-react";
import { submitRlFeedback } from "../../services/api";
import { useToast } from "../../components/Toast";
import { KEYS, storage } from "../../utils/storage";

const COOLDOWN_MS = 72 * 60 * 60 * 1000;
const FIRST_ROLL_MIN_MS = 25_000;
const FIRST_ROLL_MAX_MS = 70_000;
const NEXT_ROLL_MIN_MS = 60_000;
const NEXT_ROLL_MAX_MS = 150_000;
const DEFAULT_PROBABILITY = 0.18;
const COMMENT_MAX = 500;

const popupProbability = () => {
  const raw = Number(import.meta?.env?.VITE_FEEDBACK_PROBABILITY);
  if (Number.isFinite(raw)) return Math.max(0, Math.min(1, raw));
  return DEFAULT_PROBABILITY;
};

const randBetween = (min: number, max: number) => min + Math.random() * (max - min);

export default function FeedbackPopup({ page }: { page: string }) {
  const [open, setOpen] = useState(false);
  const [rating, setRating] = useState(0);
  const [hover, setHover] = useState(0);
  const [comment, setComment] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  // Toast.jsx is plain JS; the app-wide cast pattern (see Documents.tsx).
  const { success } = useToast() as any;

  const timerRef = useRef<number | null>(null);
  const shownRef = useRef(false); // once per session (component stays mounted)
  const activeSinceRef = useRef(Date.now());
  const pageRef = useRef(page);
  pageRef.current = page;

  useEffect(() => {
    if (typeof navigator !== "undefined" && navigator.webdriver) return;
    if (popupProbability() <= 0) return;

    const clear = () => {
      if (timerRef.current !== null) {
        window.clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };

    const schedule = (first: boolean) => {
      clear();
      const delay = first
        ? randBetween(FIRST_ROLL_MIN_MS, FIRST_ROLL_MAX_MS)
        : randBetween(NEXT_ROLL_MIN_MS, NEXT_ROLL_MAX_MS);
      timerRef.current = window.setTimeout(() => {
        if (shownRef.current) return;
        // Shared cooldown across sessions: the stored value expires via TTL.
        if (storage.get(KEYS.feedbackPopup, null) !== null) return;
        if (document.visibilityState !== "visible") {
          schedule(false);
          return;
        }
        if (Math.random() < popupProbability()) {
          shownRef.current = true;
          setOpen(true);
          return;
        }
        schedule(false);
      }, delay);
    };

    schedule(true);
    return clear;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const close = () => {
    // Any interaction (dismiss, skip, or a sent rating) starts the cooldown.
    storage.set(KEYS.feedbackPopup, Date.now(), { ttlMs: COOLDOWN_MS });
    setOpen(false);
    setRating(0);
    setHover(0);
    setComment("");
    setError("");
  };

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const send = async () => {
    if (!rating || sending) return;
    setSending(true);
    setError("");
    const res = await submitRlFeedback({
      rating,
      comment: comment.trim().slice(0, COMMENT_MAX),
      page: pageRef.current,
      context: {
        trigger: "random_popup",
        active_seconds: Math.round((Date.now() - activeSinceRef.current) / 1000),
      },
    });
    setSending(false);
    if (res.success) {
      success("Thanks — your check-in helps ARIA improve.");
      close();
    } else {
      setError("Couldn't send that right now — you can try again.");
    }
  };

  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-label="Quick feedback"
      data-testid="rl-feedback-popup"
      className="fixed bottom-4 left-4 sm:left-6 z-[70] w-[calc(100vw-2rem)] max-w-[360px] rounded-2xl border border-border bg-card text-card-foreground shadow-2xl p-4"
    >
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-sm font-semibold">Quick check-in</p>
          <p className="text-xs text-muted-foreground mt-0.5">
            How is ARIA doing? Your rating trains future rankings.
          </p>
        </div>
        <button
          type="button"
          aria-label="Dismiss feedback popup"
          className="p-1 rounded-md hover:bg-secondary text-muted-foreground"
          onClick={close}
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      <div className="mt-3 flex items-center gap-1" onMouseLeave={() => setHover(0)}>
        {[1, 2, 3, 4, 5].map((n) => (
          <button
            key={n}
            type="button"
            aria-label={`Rate ${n} of 5`}
            aria-pressed={rating === n}
            className="p-0.5 transition-transform hover:scale-110"
            onMouseEnter={() => setHover(n)}
            onFocus={() => setHover(n)}
            onBlur={() => setHover(0)}
            onClick={() => setRating(n)}
          >
            <Star
              className={`w-6 h-6 ${
                (hover || rating) >= n
                  ? "fill-amber-400 text-amber-400"
                  : "text-muted-foreground/50"
              }`}
            />
          </button>
        ))}
      </div>

      <textarea
        value={comment}
        onChange={(e) => setComment(e.target.value.slice(0, COMMENT_MAX))}
        rows={2}
        placeholder="Anything we should know? (optional)"
        className="mt-3 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-ring/40"
      />

      {error ? <p className="mt-2 text-xs text-negative">{error}</p> : null}

      <div className="mt-3 flex items-center justify-end gap-3">
        <button
          type="button"
          className="text-xs text-muted-foreground hover:text-foreground"
          onClick={close}
        >
          Not now
        </button>
        <button
          type="button"
          disabled={!rating || sending}
          className="rounded-lg bg-primary text-primary-foreground text-xs font-medium px-3 py-1.5 disabled:opacity-50 hover:opacity-90"
          onClick={send}
        >
          {sending ? "Sending…" : "Send feedback"}
        </button>
      </div>
    </div>
  );
}
