"use client";

import { useCallback, useEffect, useState } from "react";

import { useAuth } from "@/components/AuthProvider";
import { EmptyState, ErrorState, LoadingState, StatusBadge } from "@/components/States";
import type { Order, OrderStatus } from "@/lib/types";

const MODERATION_FILTER = { status: "new" as const, page: 1, size: 50 };

const missingBackendTodos = [
  "TODO backend endpoint: manual_review queue with classification confidence/manual_review fields.",
  "TODO backend endpoint: approve/reject classification and edit extracted order fields.",
  "TODO backend endpoint: audit log list for a moderation decision.",
  "TODO backend endpoint: export labeled dataset with reviewer labels and corrected fields."
];

export default function ModerationPage() {
  const { api } = useAuth();
  const [orders, setOrders] = useState<Order[]>([]);
  const [total, setTotal] = useState(0);
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
      const response = await api.getOrders(MODERATION_FILTER);
      setOrders(response.items);
      setTotal(response.total);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Не удалось загрузить очередь модерации");
    } finally {
      setIsLoading(false);
    }
  }, [api]);

  useEffect(() => {
    void load();
  }, [load]);

  async function changeStatus(order: Order, status: OrderStatus) {
    if (!api) {
      return;
    }
    setActionError(null);
    try {
      await api.updateOrderStatus(order, status);
      await load();
    } catch (reason) {
      setActionError(reason instanceof Error ? reason.message : "Не удалось применить решение");
    }
  }

  async function exportCurrentOrders() {
    if (!api) {
      return;
    }
    setActionError(null);
    try {
      const csv = await api.exportOrdersCsv({ ...MODERATION_FILTER, limit: 1000 });
      const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "orders-review-export.csv";
      link.click();
      URL.revokeObjectURL(url);
    } catch (reason) {
      setActionError(reason instanceof Error ? reason.message : "Не удалось экспортировать CSV");
    }
  }

  return (
    <section>
      <div className="page-header">
        <div>
          <h2>Manual Moderation</h2>
          <p className="muted">
            Этап 14 реализован только на существующих REST API. Специализированные backend endpoints
            не добавлялись.
          </p>
        </div>
        <div className="actions">
          <button className="secondary" onClick={exportCurrentOrders} type="button">
            Export current CSV
          </button>
          <button onClick={load} type="button">
            Обновить
          </button>
        </div>
      </div>

      <div className="panel todo-panel">
        <h3>Ограничения текущего backend API</h3>
        <p className="muted">
          Сейчас frontend может использовать только список заказов, смену order status и CSV export
          заказов. Полноценные действия moderation/dataset требуют отдельных endpoints.
        </p>
        <ul>
          {missingBackendTodos.map((todo) => (
            <li key={todo}>{todo}</li>
          ))}
        </ul>
      </div>

      {actionError ? <ErrorState message={actionError} /> : null}
      {isLoading ? <LoadingState label="Загрузка кандидатов..." /> : null}
      {error ? <ErrorState message={error} onRetry={load} /> : null}
      {!isLoading && !error && orders.length === 0 ? (
        <EmptyState label="Нет заказов в доступной MVP-очереди status=new." />
      ) : null}
      {!isLoading && !error && orders.length > 0 ? (
        <div className="panel">
          <div className="moderation-summary">
            <strong>Доступная MVP-очередь:</strong> status=new, показано {orders.length} из {total}
          </div>
          <table>
            <thead>
              <tr>
                <th>Кандидат</th>
                <th>Score</th>
                <th>Статус</th>
                <th>Контакты</th>
                <th>MVP решение</th>
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
                  <td>{order.relevance_score}</td>
                  <td>
                    <StatusBadge value={order.status} />
                  </td>
                  <td>
                    <ContactPreview contacts={order.contacts} />
                  </td>
                  <td>
                    <div className="actions">
                      <button
                        className="secondary"
                        onClick={() => changeStatus(order, "viewed")}
                        type="button"
                      >
                        Mark viewed
                      </button>
                      <button
                        className="secondary"
                        onClick={() => changeStatus(order, "contacted")}
                        type="button"
                      >
                        Mark contacted
                      </button>
                      <button
                        className="danger"
                        onClick={() => changeStatus(order, "irrelevant")}
                        type="button"
                      >
                        Reject as irrelevant
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}

function ContactPreview({ contacts }: { contacts: Order["contacts"] }) {
  if (!contacts) {
    return <span className="muted">Нет контактов</span>;
  }

  const items = Object.entries(contacts).flatMap(([kind, values]) =>
    values.map((value) => `${kind}: ${value}`)
  );

  if (items.length === 0) {
    return <span className="muted">Нет контактов</span>;
  }

  return (
    <ul className="compact-list">
      {items.slice(0, 3).map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ul>
  );
}
