import { useState } from "react";
import { registerLocalUser } from "../utils/authStorage";

function Register({ onBackToLogin }) {
  const [email, setEmail] = useState("");

  const [password, setPassword] = useState("");

  const [confirmPassword, setConfirmPassword] = useState("");

  const [loading, setLoading] = useState(false);

  const handleSubmit = async (event) => {
    event.preventDefault();

    // Email required
    if (email.trim() === "") {
      alert("Please enter your email address.");

      return;
    }

    // Password required
    if (password.trim() === "") {
      alert("Please enter a password.");

      return;
    }

    // Minimum password length
    if (password.length < 8) {
      alert("Password must contain at least 8 characters.");

      return;
    }

    // Password confirmation
    if (password !== confirmPassword) {
      alert("Passwords do not match.");

      return;
    }

    setLoading(true);

    try {
      const result = await registerLocalUser(email, password);

      if (!result.success) {
        alert(result.message || "Could not create your account.");

        return;
      }

      alert("Account created successfully. You can now sign in.");

      // Return to Login page
      onBackToLogin();
    } catch (error) {
      console.error("Registration error:", error);

      alert("ARIA could not create your account.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-page">
      <div className="login-card">
        {/* ARIA BRAND */}

        <div className="login-brand">
          <h1>ARIA</h1>

          <p>Intelligent Business Analytics</p>
        </div>

        {/* REGISTER HEADING */}

        <div className="login-heading">
          <h2>Create Account</h2>

          <p>Create your ARIA account to access your analytics workspace.</p>
        </div>

        {/* REGISTER FORM */}

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
              placeholder="Create a password"
              autoComplete="new-password"
            />
          </div>

          <div className="login-form-group">
            <label>Confirm Password</label>

            <input
              type="password"
              value={confirmPassword}
              onChange={(event) => setConfirmPassword(event.target.value)}
              placeholder="Confirm your password"
              autoComplete="new-password"
            />
          </div>

          <button type="submit" className="login-button" disabled={loading}>
            {loading ? "Creating Account..." : "Create Account"}
          </button>
        </form>

        {/* RETURN TO LOGIN */}

        <p className="login-footer">Already have an account?</p>

        <button
          type="button"
          className="register-login-link"
          onClick={onBackToLogin}
        >
          Back to Sign In
        </button>
      </div>
    </div>
  );
}

export default Register;
