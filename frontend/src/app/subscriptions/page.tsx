"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import { useAuth } from "@/components/AuthProvider";
import { EmptyState, ErrorState, LoadingState } from "@/components/States";
import type { Subscription, SubscriptionPayload } from "@/lib/types";

const emptyForm: SubscriptionPayload = {
  name: "",
  enabled: true,
  min_relevance_score: 60,
  project_types: [],
  budget_min: "",
  budget_max: "",
  currencies: [],
  source_ids: [],
  positive_keywords: [],
  negative_keywords: [],
  quiet_hours_start: "",
  quiet_hours_end: "",
  timezone: "Europe/Moscow",
  freshness_days: 7,
  max_notifications_per_period: 20,
  rate_limit_period_minutes: 60,
  similar_cooldown_minutes: 120,
  tg_chat_id: null
};

function splitCsv(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function joinCsv(values: string[]): string {
  return values.join(", ");
}

function validateForm(form: SubscriptionPayload): string | null {
  if (!form.name.trim()) {
    return "Укажите название подписки.";
  }
  if (
    form.min_relevance_score != null &&
    (form.min_relevance_score < 0 || form.min_relevance_score > 100)
  ) {
    return "min relevance должен быть от 0 до 100.";
  }
  if (form.budget_min && form.budget_max && Number(form.budget_min) > Number(form.budget_max)) {
    return "budget_min не может быть больше budget_max.";
  }
  const hasStart = Boolean(form.quiet_hours_start);
  const hasEnd = Boolean(form.quiet_hours_end);
  if (hasStart !== hasEnd) {
    return "quiet hours start/end задаются вместе.";
  }
  if (hasStart && !/^\d{2}:\d{2}$/.test(form.quiet_hours_start || "")) {
    return "quiet hours start: формат HH:MM.";
  }
  if (hasEnd && !/^\d{2}:\d{2}$/.test(form.quiet_hours_end || "")) {
    return "quiet hours end: формат HH:MM.";
  }
  if (!form.timezone.trim()) {
    return "Укажите timezone.";
  }
  return null;
}

function toPayload(form: SubscriptionPayload): SubscriptionPayload {
  return {
    ...form,
    name: form.name.trim(),
    budget_min: form.budget_min ? form.budget_min : null,
    budget_max: form.budget_max ? form.budget_max : null,
    quiet_hours_start: form.quiet_hours_start || null,
    quiet_hours_end: form.quiet_hours_end || null,
    tg_chat_id: form.tg_chat_id || null
  };
}

function fromSubscription(item: Subscription): SubscriptionPayload {
  return {
    name: item.name,
    enabled: item.enabled,
    min_relevance_score: item.min_relevance_score,
    project_types: item.project_types,
    budget_min: item.budget_min ?? "",
    budget_max: item.budget_max ?? "",
    currencies: item.currencies,
    source_ids: item.source_ids,
    positive_keywords: item.positive_keywords,
    negative_keywords: item.negative_keywords,
    quiet_hours_start: item.quiet_hours_start ?? "",
    quiet_hours_end: item.quiet_hours_end ?? "",
    timezone: item.timezone,
    freshness_days: item.freshness_days,
    max_notifications_per_period: item.max_notifications_per_period,
    rate_limit_period_minutes: item.rate_limit_period_minutes,
    similar_cooldown_minutes: item.similar_cooldown_minutes,
    tg_chat_id: null
  };
}

export default function SubscriptionsPage() {
  const { api, session } = useAuth();
  const [items, setItems] = useState<Subscription[]>([]);
  const [form, setForm] = useState<SubscriptionPayload>(emptyForm);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);

  const isAdmin = session?.role === "admin";

  const load = useCallback(async () => {
    if (!api) {
      return;
    }
    setIsLoading(true);
    setError(null);
    try {
      const response = await api.getSubscriptions(showAll && isAdmin ? { all_users: true } : {});
      setItems(response.items);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Не удалось загрузить подписки");
    } finally {
      setIsLoading(false);
    }
  }, [api, isAdmin, showAll]);

  useEffect(() => {
    void load();
  }, [load]);

  const title = useMemo(() => (editingId ? "Редактировать подписку" : "Новая подписка"), [editingId]);

  async function runAction(action: () => Promise<void>) {
    setActionError(null);
    try {
      await action();
      await load();
    } catch (reason) {
      setActionError(reason instanceof Error ? reason.message : "Действие не выполнено");
    }
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!api) {
      return;
    }
    const validationError = validateForm(form);
    if (validationError) {
      setActionError(validationError);
      return;
    }
    const payload = toPayload(form);
    await runAction(async () => {
      if (editingId) {
        await api.updateSubscription(editingId, {
          name: payload.name,
          enabled: payload.enabled,
          min_relevance_score: payload.min_relevance_score,
          project_types: payload.project_types,
          budget_min: payload.budget_min,
          budget_max: payload.budget_max,
          currencies: payload.currencies,
          source_ids: payload.source_ids,
          positive_keywords: payload.positive_keywords,
          negative_keywords: payload.negative_keywords,
          quiet_hours_start: payload.quiet_hours_start,
          quiet_hours_end: payload.quiet_hours_end,
          timezone: payload.timezone,
          freshness_days: payload.freshness_days,
          max_notifications_per_period: payload.max_notifications_per_period,
          rate_limit_period_minutes: payload.rate_limit_period_minutes,
          similar_cooldown_minutes: payload.similar_cooldown_minutes
        });
      } else {
        await api.createSubscription(payload);
      }
      setForm(emptyForm);
      setEditingId(null);
    });
  }

  return (
    <section>
      <div className="page-header">
        <div>
          <h2>Subscriptions</h2>
          <p className="muted">Персональные фильтры уведомлений, quiet hours и rate limits.</p>
        </div>
        <div className="actions">
          {isAdmin ? (
            <label className="checkbox-row">
              <input
                checked={showAll}
                onChange={(event) => setShowAll(event.target.checked)}
                type="checkbox"
              />
              Все пользователи
            </label>
          ) : null}
          <button onClick={load} type="button">
            Обновить
          </button>
        </div>
      </div>

      <div className="panel">
        <h3>{title}</h3>
        <form className="form-grid" onSubmit={onSubmit}>
          <label>
            Название
            <input
              onChange={(event) => setForm({ ...form, name: event.target.value })}
              required
              value={form.name}
            />
          </label>
          <label>
            Min relevance
            <input
              max={100}
              min={0}
              onChange={(event) =>
                setForm({
                  ...form,
                  min_relevance_score: event.target.value ? Number(event.target.value) : null
                })
              }
              type="number"
              value={form.min_relevance_score ?? ""}
            />
          </label>
          <label>
            Project types (csv)
            <input
              onChange={(event) => setForm({ ...form, project_types: splitCsv(event.target.value) })}
              placeholder="landing, bot"
              value={joinCsv(form.project_types)}
            />
          </label>
          <label>
            Currencies (csv)
            <input
              onChange={(event) => setForm({ ...form, currencies: splitCsv(event.target.value) })}
              placeholder="RUB, USD"
              value={joinCsv(form.currencies)}
            />
          </label>
          <label>
            Budget min
            <input
              onChange={(event) => setForm({ ...form, budget_min: event.target.value })}
              value={form.budget_min ?? ""}
            />
          </label>
          <label>
            Budget max
            <input
              onChange={(event) => setForm({ ...form, budget_max: event.target.value })}
              value={form.budget_max ?? ""}
            />
          </label>
          <label>
            Source IDs (csv UUID)
            <input
              onChange={(event) => setForm({ ...form, source_ids: splitCsv(event.target.value) })}
              value={joinCsv(form.source_ids)}
            />
          </label>
          <label>
            Positive keywords (csv)
            <input
              onChange={(event) =>
                setForm({ ...form, positive_keywords: splitCsv(event.target.value) })
              }
              value={joinCsv(form.positive_keywords)}
            />
          </label>
          <label>
            Negative keywords (csv)
            <input
              onChange={(event) =>
                setForm({ ...form, negative_keywords: splitCsv(event.target.value) })
              }
              value={joinCsv(form.negative_keywords)}
            />
          </label>
          <label>
            Quiet start (HH:MM)
            <input
              onChange={(event) => setForm({ ...form, quiet_hours_start: event.target.value })}
              placeholder="22:00"
              value={form.quiet_hours_start ?? ""}
            />
          </label>
          <label>
            Quiet end (HH:MM)
            <input
              onChange={(event) => setForm({ ...form, quiet_hours_end: event.target.value })}
              placeholder="07:00"
              value={form.quiet_hours_end ?? ""}
            />
          </label>
          <label>
            Timezone
            <input
              onChange={(event) => setForm({ ...form, timezone: event.target.value })}
              value={form.timezone}
            />
          </label>
          <label>
            Freshness days
            <input
              min={1}
              onChange={(event) =>
                setForm({
                  ...form,
                  freshness_days: event.target.value ? Number(event.target.value) : null
                })
              }
              type="number"
              value={form.freshness_days ?? ""}
            />
          </label>
          <label>
            Max notifications / period
            <input
              min={1}
              onChange={(event) =>
                setForm({
                  ...form,
                  max_notifications_per_period: event.target.value
                    ? Number(event.target.value)
                    : null
                })
              }
              type="number"
              value={form.max_notifications_per_period ?? ""}
            />
          </label>
          <label>
            Rate period (minutes)
            <input
              min={1}
              onChange={(event) =>
                setForm({
                  ...form,
                  rate_limit_period_minutes: Number(event.target.value || 60)
                })
              }
              type="number"
              value={form.rate_limit_period_minutes}
            />
          </label>
          <label>
            Similar cooldown (minutes)
            <input
              min={1}
              onChange={(event) =>
                setForm({
                  ...form,
                  similar_cooldown_minutes: event.target.value ? Number(event.target.value) : null
                })
              }
              type="number"
              value={form.similar_cooldown_minutes ?? ""}
            />
          </label>
          {!editingId ? (
            <label>
              Telegram chat id (optional, operator+)
              <input
                onChange={(event) =>
                  setForm({
                    ...form,
                    tg_chat_id: event.target.value ? Number(event.target.value) : null
                  })
                }
                type="number"
                value={form.tg_chat_id ?? ""}
              />
            </label>
          ) : null}
          <label className="checkbox-row">
            <input
              checked={form.enabled}
              onChange={(event) => setForm({ ...form, enabled: event.target.checked })}
              type="checkbox"
            />
            Enabled
          </label>
          <div className="actions">
            <button type="submit">{editingId ? "Сохранить" : "Создать"}</button>
            {editingId ? (
              <button
                className="secondary"
                onClick={() => {
                  setEditingId(null);
                  setForm(emptyForm);
                }}
                type="button"
              >
                Отмена
              </button>
            ) : null}
          </div>
        </form>
      </div>

      {actionError ? <ErrorState message={actionError} /> : null}
      {isLoading ? <LoadingState /> : null}
      {error ? <ErrorState message={error} onRetry={load} /> : null}
      {!isLoading && !error && items.length === 0 ? <EmptyState label="Подписок пока нет." /> : null}

      {!isLoading && !error && items.length > 0 ? (
        <div className="panel">
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Enabled</th>
                <th>Filters</th>
                <th>Quiet hours</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.id}>
                  <td>
                    <strong>{item.name}</strong>
                    <div className="muted">{item.id}</div>
                  </td>
                  <td>{item.enabled ? "on" : "off"}</td>
                  <td>
                    rel&gt;={item.min_relevance_score ?? "—"}; types=
                    {item.project_types.join(",") || "any"}; kw+=
                    {item.positive_keywords.join(",") || "—"}; kw-=
                    {item.negative_keywords.join(",") || "—"}
                  </td>
                  <td>
                    {item.quiet_hours_start && item.quiet_hours_end
                      ? `${item.quiet_hours_start}-${item.quiet_hours_end} ${item.timezone}`
                      : item.timezone}
                  </td>
                  <td>
                    <div className="actions">
                      <button
                        className="secondary"
                        onClick={() => {
                          setEditingId(item.id);
                          setForm(fromSubscription(item));
                        }}
                        type="button"
                      >
                        Edit
                      </button>
                      <button
                        className="secondary"
                        onClick={() =>
                          void runAction(async () => {
                            if (item.enabled) {
                              await api!.disableSubscription(item.id);
                            } else {
                              await api!.enableSubscription(item.id);
                            }
                          })
                        }
                        type="button"
                      >
                        {item.enabled ? "Disable" : "Enable"}
                      </button>
                      <button
                        className="secondary"
                        onClick={() =>
                          void runAction(async () => {
                            await api!.deleteSubscription(item.id);
                          })
                        }
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
        </div>
      ) : null}
    </section>
  );
}
