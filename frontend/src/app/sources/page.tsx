"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";

import { useAuth } from "@/components/AuthProvider";
import { EmptyState, ErrorState, LoadingState, StatusBadge } from "@/components/States";
import type { Source } from "@/lib/types";

export default function SourcesPage() {
  const { api } = useAuth();
  const [sources, setSources] = useState<Source[]>([]);
  const [total, setTotal] = useState(0);
  const [q, setQ] = useState("");
  const [link, setLink] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!api) {
      return;
    }
    setIsLoading(true);
    setError(null);
    try {
      const response = await api.getSources({ q: q || undefined, page: 1, size: 100 });
      setSources(response.items);
      setTotal(response.total);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Не удалось загрузить источники");
    } finally {
      setIsLoading(false);
    }
  }, [api, q]);

  useEffect(() => {
    void load();
  }, [load]);

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!api || !link.trim()) {
      return;
    }
    setActionError(null);
    try {
      await api.createSource(link.trim());
      setLink("");
      await load();
    } catch (reason) {
      setActionError(reason instanceof Error ? reason.message : "Не удалось создать источник");
    }
  }

  async function runAction(action: () => Promise<void>) {
    setActionError(null);
    try {
      await action();
      await load();
    } catch (reason) {
      setActionError(reason instanceof Error ? reason.message : "Действие не выполнено");
    }
  }

  return (
    <section>
      <div className="page-header">
        <div>
          <h2>Sources</h2>
          <p className="muted">Добавление и управление публичными Telegram источниками.</p>
        </div>
        <button onClick={load} type="button">
          Обновить
        </button>
      </div>

      <form className="panel form-grid" onSubmit={create}>
        <label>
          Новый источник
          <input
            onChange={(event) => setLink(event.target.value)}
            placeholder="https://t.me/public_channel"
            value={link}
          />
        </label>
        <div className="actions">
          <button type="submit">Добавить</button>
        </div>
      </form>

      <div className="panel filters">
        <label>
          Поиск
          <input
            onChange={(event) => setQ(event.target.value)}
            placeholder="username"
            value={q}
          />
        </label>
      </div>

      {actionError ? <ErrorState message={actionError} /> : null}
      {isLoading ? <LoadingState /> : null}
      {error ? <ErrorState message={error} onRetry={load} /> : null}
      {!isLoading && !error && sources.length === 0 ? <EmptyState label="Источники не найдены." /> : null}
      {!isLoading && !error && sources.length > 0 ? (
        <div className="panel">
          <table>
            <thead>
              <tr>
                <th>Источник</th>
                <th>Доступ</th>
                <th>Активность</th>
                <th>Последнее сообщение</th>
                <th>Действия</th>
              </tr>
            </thead>
            <tbody>
              {sources.map((source) => (
                <tr key={source.id}>
                  <td>
                    <strong>{source.normalized_username ?? source.username ?? source.id}</strong>
                    <p className="muted small">{source.title ?? source.type}</p>
                  </td>
                  <td>
                    <StatusBadge value={source.access_status} />
                    <p className="small">{source.enabled ? "enabled" : "disabled"}</p>
                  </td>
                  <td>
                    {source.activity_score} · {source.activity_status}
                  </td>
                  <td>{source.last_seen_message_id}</td>
                  <td>
                    <div className="actions">
                      <button
                        className="secondary"
                        onClick={() => runAction(() => api!.validateSource(source.id).then(() => undefined))}
                        type="button"
                      >
                        Validate
                      </button>
                      <button
                        className="secondary"
                        onClick={() =>
                          runAction(() => api!.updateSource(source.id, !source.enabled).then(() => undefined))
                        }
                        type="button"
                      >
                        {source.enabled ? "Disable" : "Enable"}
                      </button>
                      <button
                        className="danger"
                        onClick={() => runAction(() => api!.deleteSource(source.id))}
                        type="button"
                      >
                        Delete
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="muted small">Всего: {total}</p>
        </div>
      ) : null}
    </section>
  );
}
