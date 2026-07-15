"use client";

import { useCallback, useEffect, useState } from "react";

import { useAuth } from "@/components/AuthProvider";
import { EmptyState, ErrorState, LoadingState } from "@/components/States";
import type { StatsSummary } from "@/lib/types";

export default function StatisticsPage() {
  const { api } = useAuth();
  const [stats, setStats] = useState<StatsSummary | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!api) {
      return;
    }
    setIsLoading(true);
    setError(null);
    try {
      setStats(await api.getStatsSummary());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Не удалось загрузить статистику");
    } finally {
      setIsLoading(false);
    }
  }, [api]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <section>
      <div className="page-header">
        <div>
          <h2>Statistics</h2>
          <p className="muted">MVP summary по заказам, источникам, классам и статусам.</p>
        </div>
        <button onClick={load} type="button">
          Обновить
        </button>
      </div>

      {isLoading ? <LoadingState /> : null}
      {error ? <ErrorState message={error} onRetry={load} /> : null}
      {!isLoading && !error && !stats ? <EmptyState label="Статистика отсутствует." /> : null}
      {stats ? (
        <>
          <div className="stats-grid">
            <div className="panel">
              <span className="muted">Orders</span>
              <p className="stat-value">{stats.orders_total}</p>
            </div>
            <div className="panel">
              <span className="muted">Sources</span>
              <p className="stat-value">{stats.sources_total}</p>
            </div>
          </div>
          <div className="stats-grid">
            <StatsMap title="Classes" values={stats.classes} />
            <StatsMap title="Order statuses" values={stats.order_statuses} />
          </div>
        </>
      ) : null}
    </section>
  );
}

function StatsMap({ title, values }: { title: string; values: Record<string, number> }) {
  const entries = Object.entries(values);
  return (
    <div className="panel">
      <h3>{title}</h3>
      {entries.length === 0 ? (
        <EmptyState label="Нет данных." />
      ) : (
        <table>
          <tbody>
            {entries.map(([key, value]) => (
              <tr key={key}>
                <td>{key}</td>
                <td>{value}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
