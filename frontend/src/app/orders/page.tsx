"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import { useAuth } from "@/components/AuthProvider";
import { EmptyState, ErrorState, LoadingState, StatusBadge } from "@/components/States";
import type { Order, OrderFilters, OrderStatus } from "@/lib/types";

const orderStatuses: OrderStatus[] = ["new", "viewed", "contacted", "irrelevant", "archived"];
const nextStatuses: OrderStatus[] = ["viewed", "contacted", "irrelevant", "archived"];

export default function OrdersPage() {
  const { api } = useAuth();
  const [filters, setFilters] = useState<OrderFilters>({ page: 1, size: 20 });
  const [draft, setDraft] = useState<OrderFilters>({ page: 1, size: 20 });
  const [orders, setOrders] = useState<Order[]>([]);
  const [favoriteIds, setFavoriteIds] = useState<Set<string>>(new Set());
  const [total, setTotal] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const canLoad = Boolean(api);

  const load = useCallback(async () => {
    if (!api) {
      return;
    }
    setIsLoading(true);
    setError(null);
    try {
      const [ordersResponse, favoritesResponse] = await Promise.all([
        api.getOrders(filters),
        api.getFavorites()
      ]);
      setOrders(ordersResponse.items);
      setTotal(ordersResponse.total);
      setFavoriteIds(new Set(favoritesResponse.items.map((favorite) => favorite.order_id)));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Не удалось загрузить заказы");
    } finally {
      setIsLoading(false);
    }
  }, [api, filters]);

  useEffect(() => {
    void load();
  }, [load]);

  function submitFilters(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFilters({ ...draft, page: 1, size: 20 });
  }

  async function changeStatus(order: Order, status: OrderStatus) {
    if (!api) {
      return;
    }
    setActionError(null);
    try {
      await api.updateOrderStatus(order, status);
      await load();
    } catch (reason) {
      setActionError(reason instanceof Error ? reason.message : "Не удалось изменить статус");
    }
  }

  async function toggleFavorite(order: Order) {
    if (!api) {
      return;
    }
    setActionError(null);
    try {
      if (favoriteIds.has(order.id)) {
        await api.removeFavorite(order.id);
      } else {
        await api.addFavorite(order.id);
      }
      await load();
    } catch (reason) {
      setActionError(reason instanceof Error ? reason.message : "Не удалось изменить избранное");
    }
  }

  const pageCount = useMemo(() => Math.max(1, Math.ceil(total / (filters.size ?? 20))), [filters.size, total]);

  return (
    <section>
      <div className="page-header">
        <div>
          <h2>Orders</h2>
          <p className="muted">Фильтры, статусы и избранное на реальных API endpoints.</p>
        </div>
        <button onClick={load} type="button">
          Обновить
        </button>
      </div>

      <form className="panel filters" onSubmit={submitFilters}>
        <label>
          Поиск
          <input
            onChange={(event) => setDraft({ ...draft, q: event.target.value || undefined })}
            placeholder="лендинг, CRM..."
            value={draft.q ?? ""}
          />
        </label>
        <label>
          Статус
          <select
            onChange={(event) =>
              setDraft({ ...draft, status: (event.target.value || undefined) as OrderStatus | undefined })
            }
            value={draft.status ?? ""}
          >
            <option value="">Все</option>
            {orderStatuses.map((status) => (
              <option key={status} value={status}>
                {status}
              </option>
            ))}
          </select>
        </label>
        <label>
          Тип проекта
          <input
            onChange={(event) => setDraft({ ...draft, project_type: event.target.value || undefined })}
            placeholder="landing_page"
            value={draft.project_type ?? ""}
          />
        </label>
        <label>
          Relevance от
          <input
            min={0}
            max={100}
            onChange={(event) =>
              setDraft({ ...draft, relevance_min: event.target.value ? Number(event.target.value) : undefined })
            }
            type="number"
            value={draft.relevance_min ?? ""}
          />
        </label>
        <label>
          Source ID
          <input
            onChange={(event) => setDraft({ ...draft, source_id: event.target.value || undefined })}
            value={draft.source_id ?? ""}
          />
        </label>
        <label>
          Дата от
          <input
            onChange={(event) => setDraft({ ...draft, date_from: event.target.value || undefined })}
            type="date"
            value={draft.date_from ?? ""}
          />
        </label>
        <label>
          Дата до
          <input
            onChange={(event) => setDraft({ ...draft, date_to: event.target.value || undefined })}
            type="date"
            value={draft.date_to ?? ""}
          />
        </label>
        <label>
          Бюджет от
          <input
            min={0}
            onChange={(event) =>
              setDraft({ ...draft, budget_min: event.target.value ? Number(event.target.value) : undefined })
            }
            type="number"
            value={draft.budget_min ?? ""}
          />
        </label>
        <div className="actions">
          <button type="submit">Применить</button>
          <button
            className="secondary"
            onClick={() => {
              setDraft({ page: 1, size: 20 });
              setFilters({ page: 1, size: 20 });
            }}
            type="button"
          >
            Сбросить
          </button>
        </div>
      </form>

      {actionError ? <ErrorState message={actionError} /> : null}
      {!canLoad || isLoading ? <LoadingState /> : null}
      {error ? <ErrorState message={error} onRetry={load} /> : null}
      {!isLoading && !error && orders.length === 0 ? <EmptyState label="Заказы не найдены." /> : null}
      {!isLoading && !error && orders.length > 0 ? (
        <div className="panel">
          <table>
            <thead>
              <tr>
                <th>Заказ</th>
                <th>Бюджет</th>
                <th>Score</th>
                <th>Статус</th>
                <th>Действия</th>
              </tr>
            </thead>
            <tbody>
              {orders.map((order) => (
                <tr key={order.id}>
                  <td>
                    <strong>{order.title ?? order.project_type ?? "Без названия"}</strong>
                    <p className="small">{order.summary ?? "Описание отсутствует"}</p>
                    <p className="muted small">
                      {new Date(order.published_at).toLocaleString()} · {order.project_type ?? "type n/a"}
                    </p>
                    {order.message_url ? (
                      <a href={order.message_url} rel="noreferrer" target="_blank">
                        Оригинал
                      </a>
                    ) : null}
                  </td>
                  <td>
                    {order.budget_from ?? "?"} - {order.budget_to ?? "?"} {order.budget_currency ?? ""}
                  </td>
                  <td>{order.relevance_score}</td>
                  <td>
                    <StatusBadge value={order.status} />
                  </td>
                  <td>
                    <div className="actions">
                      <button className="secondary" onClick={() => toggleFavorite(order)} type="button">
                        {favoriteIds.has(order.id) ? "Убрать из избранного" : "В избранное"}
                      </button>
                      <select
                        aria-label="Изменить статус"
                        onChange={(event) => {
                          if (event.target.value) {
                            void changeStatus(order, event.target.value as OrderStatus);
                          }
                        }}
                        value=""
                      >
                        <option value="">Статус...</option>
                        {nextStatuses.map((status) => (
                          <option key={status} value={status}>
                            {status}
                          </option>
                        ))}
                      </select>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="actions" style={{ marginTop: 14 }}>
            <button
              className="secondary"
              disabled={(filters.page ?? 1) <= 1}
              onClick={() => setFilters({ ...filters, page: (filters.page ?? 1) - 1 })}
              type="button"
            >
              Назад
            </button>
            <span className="muted small">
              Страница {filters.page ?? 1} из {pageCount}, всего {total}
            </span>
            <button
              className="secondary"
              disabled={(filters.page ?? 1) >= pageCount}
              onClick={() => setFilters({ ...filters, page: (filters.page ?? 1) + 1 })}
              type="button"
            >
              Вперёд
            </button>
          </div>
        </div>
      ) : null}
    </section>
  );
}
