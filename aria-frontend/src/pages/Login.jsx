import { useState } from "react";
import { authenticateLocalUser } from "../utils/authStorage";

function Login({ onLogin, onCreateAccount }) {
  const [email, setEmail] = useState("");

  const [password, setPassword] = useState("");

  const [loading, setLoading] = useState(false);

  const handleSubmit = async (event) => {
    event.preventDefault();

    if (email.trim() === "" || password.trim() === "") {
      alert("Please enter your email and password.");

      return;
    }

    setLoading(true);

    try {
      const result = await authenticateLocalUser(email, password);
      if (!result.success) {
        alert(result.message || "Unable to sign in.");

        // If the email is not registered,
        // send the user to Create Account.
        if (result.code === "USER_NOT_FOUND") {
          onCreateAccount();
        }

        return;
      }

      onLogin(result.user);
    } catch (error) {
      console.error("Login error:", error);

      alert("ARIA could not sign you in.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-brand">
          <h1>ARIA</h1>

          <p>Intelligent Business Analytics</p>
        </div>

        <div className="login-heading">
          <h2>Welcome Back</h2>

          <p>Sign in to continue to your analytics workspace.</p>
        </div>

        <form className="login-form" onSubmit={handleSubmit}>
          <div className="login-form-group">
            <label>Email Address</label>

            <input
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="Enter your email"
              autoComplete="email"
            />
          </div>

          <div className="login-form-group">
            <label>Password</label>

            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="Enter your password"
              autoComplete="current-password"
            />
          </div>

          <button type="submit" className="login-button" disabled={loading}>
            {loading ? "Signing In..." : "Sign In"}
          </button>
        </form>

        <p className="login-footer">Don't have an account?</p>

        <button
          type="button"
          className="register-login-link"
          onClick={onCreateAccount}
        >
          Create Account
        </button>
      </div>
    </div>
  );
}

export default Login;
