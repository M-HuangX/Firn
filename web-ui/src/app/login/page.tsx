"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/hooks/use-auth";
import { FirnLogo } from "@/components/layout/firn-logo";

export default function LoginPage() {
  const { login } = useAuth();
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      await login(password);
      router.push("/");
    } catch {
      setError("Invalid password. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex items-center justify-center min-h-[calc(100vh-8rem)]">
      <div className="w-full max-w-sm mx-4">
        <div className="bg-surface rounded-xl border border-border p-8">
          {/* Logo */}
          <div className="text-center mb-8">
            <div className="flex justify-center mb-3">
              <FirnLogo size={40} />
            </div>
            <h1 className="text-xl font-semibold text-text-primary">
              Firn
            </h1>
            <p className="text-sm text-text-secondary mt-1">
              Sign in to access admin features
            </p>
          </div>

          {/* Form */}
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label
                htmlFor="password"
                className="block text-sm font-medium text-text-secondary mb-1.5"
              >
                Password
              </label>
              <input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Enter admin password"
                autoFocus
                className="w-full h-11 px-4 rounded-lg bg-background border border-border text-text-primary placeholder:text-text-secondary text-sm outline-none focus:border-accent/50 focus:ring-1 focus:ring-accent/30 transition-colors"
              />
            </div>

            {error && (
              <p className="text-sm text-negative">{error}</p>
            )}

            <button
              type="submit"
              disabled={loading || !password}
              className="w-full h-11 rounded-lg bg-accent text-background font-medium text-sm hover:bg-accent/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {loading ? "Signing in..." : "Sign in as Admin"}
            </button>
          </form>

          <p className="text-xs text-text-secondary text-center mt-6">
            Read-only access is available without signing in.
          </p>
        </div>
      </div>
    </div>
  );
}
