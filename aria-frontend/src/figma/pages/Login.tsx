import { useEffect, useState } from "react";
import { Eye, EyeOff } from "lucide-react";
import {
  authenticateLocalUser,
  registerLocalUser,
  resendVerificationEmail,
  verifyEmailAddress,
} from "../../utils/authStorage";
import AriaLogo from "../components/AriaLogo";

interface LoginProps {
  onLogin: () => void;
}

export default function Login({ onLogin }: LoginProps) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [passwordVisible, setPasswordVisible] = useState(false);
  const [confirmPasswordVisible, setConfirmPasswordVisible] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [verificationEmail, setVerificationEmail] = useState("");

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const token = params.get("verify_email");
    if (!token) return;
    window.history.replaceState(null, "", `${window.location.pathname}${window.location.hash}`);
    setLoading(true);
    void verifyEmailAddress(token)
      .then((result) => {
        setMode("login");
        setNotice(result.message || "Email verified. You can now sign in.");
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "Email verification failed.");
      })
      .finally(() => setLoading(false));
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");

    const identity = email.trim();
    setNotice("");
    if (identity === "" || password.trim() === "") {
      setError("Please enter your email and password.");
      return;
    }
    const isEmail = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(identity);
    if (!isEmail) {
      setError("Please enter a valid email address.");
      return;
    }
    setVerificationEmail("");

    setLoading(true);
    try {
      if (mode === "register") {
        if (password !== confirmPassword) {
          setError("Passwords do not match");
          setLoading(false);
          return;
        }
        if (password.length < 8) {
          setError("Password must be at least 8 characters");
          setLoading(false);
          return;
        }
        const reg = await registerLocalUser(email, password);
        if (!reg.success) {
          setError(reg.message || "Could not create your account.");
          setLoading(false);
          return;
        }
        setMode("login");
        if (reg.verificationRequired) {
          setVerificationEmail(email.trim());
          setNotice(reg.message || "Check your email for a verification link before signing in.");
        } else {
          setVerificationEmail("");
          setNotice(reg.message || "Account created. You can now sign in.");
        }
        return;
      }

      const result = await authenticateLocalUser(email, password);
      if (!result.success) {
        setError(result.message || "Unable to sign in.");
        if (result.needsVerification) setVerificationEmail(email.trim());
        return;
      }
      onLogin();
    } catch (err) {
      setError("ARIA could not sign you in. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  const resendVerification = async () => {
    setLoading(true);
    setError("");
    try {
      const result = await resendVerificationEmail(verificationEmail);
      setNotice(result.message || "If verification is needed, a new link has been sent.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not resend the verification email.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-page login-page--signin">
      <div className="login-shell">
        {/* ─── LEFT: ARIA VISUAL AREA ─── */}
        <aside className="login-showcase" aria-hidden="true">
          <div className="login-showcase-brand">
            <AriaLogo size={40} />
            <div>
              <strong>ARIA</strong>
              <span>Intelligent Business Analytics</span>
            </div>
          </div>

          <div className="login-showcase-center">
            <div className="login-showcase-copy">
              <h3>
                Turn your data
                <br />
                into smarter decisions.
              </h3>
              <p>
                Ask business questions in plain language, explore your data,
                and uncover meaningful insights with ARIA.
              </p>
            </div>

            <div className="login-stage" aria-hidden="true">
              <div className="login-focal">
                <span className="login-focal-ring" />
                <span className="login-focal-symbol">✦</span>
                <span className="login-focal-signal login-focal-signal--in" />
                <span className="login-focal-signal login-focal-signal--out" />
              </div>

              <div className="login-kpi">
                <span className="login-float-label">Intelligence</span>
                <strong className="login-kpi-value">ARIA Agents</strong>
                <span className="login-kpi-delta">Ask · Explore · Decide</span>
              </div>

              <div className="login-chart">
                <span className="login-float-label">Schema Discovery</span>
                <svg
                  className="login-chart-svg"
                  viewBox="0 0 140 44"
                  preserveAspectRatio="none"
                  aria-hidden="true"
                >
                  <polyline
                    className="login-chart-line"
                    points="0,36 26,30 48,32 74,15 100,19 140,6"
                  />
                  <circle className="login-chart-dot" cx="0" cy="36" r="3" />
                </svg>
              </div>

              <div className="login-insight">
                <span className="login-float-tag">ARIA</span>
                <span className="login-insight-text">
                  Natural-language analytics
                </span>
              </div>
            </div>
          </div>

          <div className="login-showcase-bottom">
            <ul className="login-showcase-features">
              <li>Connect your databases &amp; files</li>
              <li>Explore your schema automatically</li>
              <li>Ask questions without SQL</li>
            </ul>
            <div className="login-showcase-footer">
              Secure intelligent analytics · ARIA
            </div>
          </div>
        </aside>

        {/* ─── RIGHT: LOGIN / REGISTER AREA ─── */}
        <div className="login-card">
          <div className="login-card-brand">
            <span className="login-card-mark">
              <AriaLogo mono size={20} />
            </span>
            <span className="login-card-wordmark">ARIA</span>
          </div>

          <div className="login-heading">
            <h2>{mode === "login" ? "Welcome back" : "Create account"}</h2>
            <p>
              {mode === "login"
                ? "Sign in to your ARIA workspace"
                : "Get started with ARIA Intelligence"}
            </p>
          </div>

          <form className="login-form" onSubmit={handleSubmit} noValidate>
            {error && (
              <p className="login-error" role="alert">{error}</p>
            )}
            {notice && (
              <p className="login-success" role="status">{notice}</p>
            )}
            {verificationEmail && mode === "login" && (
              <button
                type="button"
                className="login-forgot"
                onClick={() => void resendVerification()}
                disabled={loading}
              >
                Resend verification email
              </button>
            )}

            <div className="login-form-group">
              <label htmlFor="login-email">
                Email Address
              </label>
              <input
                id="login-email"
                type="email"
                value={email}
                onChange={(e) => { setEmail(e.target.value); setError(""); setNotice(""); }}
                placeholder="you@company.com"
                autoComplete="email"
                aria-invalid={error ? "true" : undefined}
              />
            </div>

            <div className="login-form-group">
              <div className="login-label-row">
                <label htmlFor="login-password">Password</label>
              </div>
              <div className="login-password-field">
                <input
                  id="login-password"
                  type={passwordVisible ? "text" : "password"}
                  value={password}
                  onChange={(e) => { setPassword(e.target.value); setError(""); }}
                  placeholder="Enter your password"
                  autoComplete={mode === "login" ? "current-password" : "new-password"}
                  aria-invalid={error ? "true" : undefined}
                />
                <button
                  type="button"
                  className="login-password-toggle"
                  aria-label={passwordVisible ? "Hide password" : "Show password"}
                  aria-pressed={passwordVisible}
                  onClick={(event) => {
                      event.preventDefault();
                      event.stopPropagation();
                      setPasswordVisible((visible) => !visible);
                    }}
                >
                  {passwordVisible
                    ? <EyeOff size={18} aria-hidden="true" />
                    : <Eye size={18} aria-hidden="true" />}
                </button>
              </div>
            </div>

            {mode === "register" && (
              <div className="login-form-group">
                <label htmlFor="login-confirm">Confirm Password</label>
                <div className="login-password-field">
                  <input
                    id="login-confirm"
                    type={confirmPasswordVisible ? "text" : "password"}
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    placeholder="Confirm your password"
                    autoComplete="new-password"
                  />
                  <button
                    type="button"
                    className="login-password-toggle"
                    aria-label={confirmPasswordVisible ? "Hide confirm password" : "Show confirm password"}
                    aria-pressed={confirmPasswordVisible}
                    onClick={(event) => {
                      event.preventDefault();
                      event.stopPropagation();
                      setConfirmPasswordVisible((visible) => !visible);
                    }}
                  >
                    {confirmPasswordVisible
                      ? <EyeOff size={18} aria-hidden="true" />
                      : <Eye size={18} aria-hidden="true" />}
                  </button>
                </div>
              </div>
            )}

            <button
              type="submit"
              className={`login-button ${loading ? "is-loading" : ""}`}
              disabled={loading}
            >
              {loading ? (
                <span className="login-button-loading">
                  <span className="login-button-spinner" aria-hidden="true" />
                  {mode === "login" ? "Signing in…" : "Creating account…"}
                </span>
              ) : (
                <span>
                  {mode === "login" ? "Access Intelligence Hub" : "Create Account"}{" "}
                  <span aria-hidden="true">→</span>
                </span>
              )}
            </button>
          </form>

          <div className="login-footer">
            <span>{mode === "login" ? "New here?" : "Already have an account?"}</span>
            <button
              type="button"
              className="register-login-link"
              onClick={() => {
                setMode(mode === "login" ? "register" : "login");
                setError("");
                setNotice("");
                setVerificationEmail("");
              }}
            >
              {mode === "login" ? "Create Account" : "Sign In"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
