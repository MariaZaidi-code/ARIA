import { useEffect, useState } from "react";
import { authenticateLocalUser } from "../utils/authStorage";

function Login({ onLogin, onCreateAccount }) {
  const [email, setEmail] = useState("");

  const [password, setPassword] = useState("");

  const [loading, setLoading] = useState(false);

  const [error, setError] = useState("");

  const [kpi, setKpi] = useState(0);

  useEffect(() => {
    const end = 128420;
    const prefersReduced = window.matchMedia(
      "(prefers-reduced-motion: reduce)"
    ).matches;

    const start = performance.now();
    const duration = 1400;
    let raf;

    const tick = (now) => {
      const t = prefersReduced ? 1 : Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      setKpi(Math.round(eased * end));

      if (!prefersReduced && t < 1) {
        raf = requestAnimationFrame(tick);
      }
    };

    raf = requestAnimationFrame(tick);

    return () => cancelAnimationFrame(raf);
  }, []);

  const handleSubmit = async (event) => {
    event.preventDefault();
    setError("");

    if (email.trim() === "" || password.trim() === "") {
      setError("Please enter your email and password.");

      return;
    }

    setLoading(true);

    try {
      const result = await authenticateLocalUser(email, password);
      if (!result.success) {
        setError(result.message || "Unable to sign in.");

        if (result.code === "USER_NOT_FOUND") {
          onCreateAccount();
        }

        return;
      }

      onLogin(result.user);
    } catch (err) {
      console.error("Login error:", err);

      setError("ARIA could not sign you in. Please try again.");
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
              {/* ARIA intelligence node */}
              <div className="login-focal">
                <span className="login-focal-ring" />
                <span className="login-focal-symbol">✦</span>
                <span className="login-focal-signal login-focal-signal--in" />
                <span className="login-focal-signal login-focal-signal--out" />
              </div>

              {/* Mini revenue KPI */}
              <div className="login-kpi">
                <span className="login-float-label">Revenue</span>
                <strong className="login-kpi-value">${kpi.toLocaleString("en-US")}</strong>
                <span className="login-kpi-delta">↑ 18.4%</span>
              </div>

              {/* Small trend chart */}
              <div className="login-chart">
                <span className="login-float-label">Revenue Trend</span>
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

              {/* Insight card */}
              <div className="login-insight">
                <span className="login-float-tag">INSIGHT</span>
                <span className="login-insight-text">
                  Growth driven by Product A
                </span>
              </div>
            </div>
          </div>

          <div className="login-showcase-bottom">
            <ul className="login-showcase-features">
              <li>Connect your databases &amp; files</li>

              <li>Explore your schema automatically</li>

              <li>Discover insights without SQL</li>
            </ul>

            <div className="login-showcase-footer">
              Secure intelligent analytics · ARIA
            </div>
          </div>
        </aside>

        {/* ─── RIGHT: LOGIN AREA ─── */}
        <div className="login-card">
          <div className="login-card-brand">
            <span className="login-card-mark">✦</span>
            <span className="login-card-wordmark">ARIA</span>
          </div>

          <div className="login-heading">
            <span className="login-eyebrow">INTELLIGENT ANALYTICS</span>

            <h2>Welcome back</h2>

            <p>Sign in to continue to your ARIA workspace.</p>
          </div>

          <form className="login-form" onSubmit={handleSubmit} noValidate>
            {error ? (
              <p className="login-error" role="alert">
                {error}
              </p>
            ) : null}

            <div className="login-form-group">
              <label htmlFor="login-email">Email Address</label>

              <input
                id="login-email"
                type="email"
                value={email}
                onChange={(event) => {
                  setEmail(event.target.value);
                  setError("");
                }}
                placeholder="you@company.com"
                autoComplete="email"
                aria-invalid={error ? "true" : undefined}
              />
            </div>

            <div className="login-form-group">
              <div className="login-label-row">
                <label htmlFor="login-password">Password</label>

                <a className="login-forgot" href="#forgot">
                  Forgot password?
                </a>
              </div>

              <input
                id="login-password"
                type="password"
                value={password}
                onChange={(event) => {
                  setPassword(event.target.value);
                  setError("");
                }}
                placeholder="Enter your password"
                autoComplete="current-password"
                aria-invalid={error ? "true" : undefined}
              />
            </div>

            <button
              type="submit"
              className={`login-button ${loading ? "is-loading" : ""}`}
              disabled={loading}
            >
              {loading ? (
                <span className="login-button-loading">
                  <span className="login-button-spinner" aria-hidden="true" />
                  Signing in…
                </span>
              ) : (
                <span>
                  Sign In <span aria-hidden="true">→</span>
                </span>
              )}
            </button>
          </form>

          <div className="login-footer">
            <span>Don&apos;t have an account?</span>

            <button
              type="button"
              className="register-login-link"
              onClick={onCreateAccount}
            >
              Create Account
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default Login;