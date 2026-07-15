"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";

import { createDefaultSession, useAuth } from "@/components/AuthProvider";
import type { Role } from "@/lib/types";

export default function LoginPage() {
  const router = useRouter();
  const { login } = useAuth();
  const [form, setForm] = useState(createDefaultSession);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    login({
      apiBaseUrl: form.apiBaseUrl.replace(/\/$/, ""),
      apiKey: form.apiKey,
      role: form.role
    });
    router.replace("/orders");
  }

  return (
    <main className="login-page">
      <form className="login-card" onSubmit={submit}>
        <h1>TG Order Radar</h1>
        <p className="muted">
          Минимальный вход: укажите API URL и ключ из backend env. OAuth/JWT не добавляется на этом
          этапе.
        </p>
        <div className="form-grid">
          <label>
            API URL
            <input
              onChange={(event) => setForm({ ...form, apiBaseUrl: event.target.value })}
              required
              value={form.apiBaseUrl}
            />
          </label>
          <label>
            X-API-Key
            <input
              onChange={(event) => setForm({ ...form, apiKey: event.target.value })}
              placeholder="dev-admin-key"
              required
              type="password"
              value={form.apiKey}
            />
          </label>
          <label>
            Role hint
            <select
              onChange={(event) => setForm({ ...form, role: event.target.value as Role })}
              value={form.role}
            >
              <option value="admin">admin</option>
              <option value="operator">operator</option>
              <option value="viewer">viewer</option>
            </select>
          </label>
        </div>
        <div className="actions" style={{ marginTop: 16 }}>
          <button type="submit">Войти</button>
        </div>
      </form>
    </main>
  );
}
