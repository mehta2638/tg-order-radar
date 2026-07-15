"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";

import { useAuth } from "@/components/AuthProvider";
import { EmptyState, ErrorState, LoadingState } from "@/components/States";
import type { Keyword, KeywordPayload, NegativeKeyword } from "@/lib/types";

const defaultPositive: KeywordPayload = {
  phrase: "",
  lang: "ru",
  weight: 1,
  category: "general",
  is_regex: false,
  enabled: true
};

const defaultNegative = {
  phrase: "",
  lang: "ru",
  weight: 1,
  is_regex: false,
  enabled: true
};

export default function KeywordsPage() {
  const { api } = useAuth();
  const [keywords, setKeywords] = useState<Keyword[]>([]);
  const [negativeKeywords, setNegativeKeywords] = useState<NegativeKeyword[]>([]);
  const [positiveForm, setPositiveForm] = useState(defaultPositive);
  const [negativeForm, setNegativeForm] = useState(defaultNegative);
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
      const [positive, negative] = await Promise.all([
        api.getKeywords(),
        api.getNegativeKeywords()
      ]);
      setKeywords(positive.items);
      setNegativeKeywords(negative.items);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Не удалось загрузить словари");
    } finally {
      setIsLoading(false);
    }
  }, [api]);

  useEffect(() => {
    void load();
  }, [load]);

  async function createPositive(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!api) {
      return;
    }
    await runAction(async () => {
      await api.createKeyword(positiveForm);
      setPositiveForm(defaultPositive);
    });
  }

  async function createNegative(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!api) {
      return;
    }
    await runAction(async () => {
      await api.createNegativeKeyword(negativeForm);
      setNegativeForm(defaultNegative);
    });
  }

  async function runAction(action: () => Promise<void>) {
    setActionError(null);
    try {
      await action();
      await load();
    } catch (reason) {
      setActionError(reason instanceof Error ? reason.message : "Действие со словарём не выполнено");
    }
  }

  return (
    <section>
      <div className="page-header">
        <div>
          <h2>Keywords</h2>
          <p className="muted">Позитивные и негативные словари с Redis hot reload на backend.</p>
        </div>
        <button onClick={load} type="button">
          Обновить
        </button>
      </div>

      <div className="panel">
        <h3>Positive keyword</h3>
        <form className="form-grid" onSubmit={createPositive}>
          <KeywordInputs
            includeCategory
            onChange={(next) => setPositiveForm(next as KeywordPayload)}
            value={positiveForm}
          />
          <div className="actions">
            <button type="submit">Создать</button>
          </div>
        </form>
      </div>

      <div className="panel">
        <h3>Negative keyword</h3>
        <form className="form-grid" onSubmit={createNegative}>
          <KeywordInputs onChange={setNegativeForm} value={negativeForm} />
          <div className="actions">
            <button type="submit">Создать</button>
          </div>
        </form>
      </div>

      {actionError ? <ErrorState message={actionError} /> : null}
      {isLoading ? <LoadingState /> : null}
      {error ? <ErrorState message={error} onRetry={load} /> : null}
      {!isLoading && !error && keywords.length === 0 && negativeKeywords.length === 0 ? (
        <EmptyState label="Словари пустые." />
      ) : null}
      {!isLoading && !error ? (
        <div className="panel">
          <h3>Positive</h3>
          <KeywordTable
            items={keywords}
            onDelete={(id) => runAction(() => api!.deleteKeyword(id))}
            onToggle={(item) =>
              runAction(() =>
                api!.updateKeyword(item.id, { enabled: !item.enabled }).then(() => undefined)
              )
            }
          />
          <h3>Negative</h3>
          <KeywordTable
            items={negativeKeywords}
            onDelete={(id) => runAction(() => api!.deleteNegativeKeyword(id))}
            onToggle={(item) =>
              runAction(() =>
                api!.updateNegativeKeyword(item.id, { enabled: !item.enabled }).then(() => undefined)
              )
            }
          />
        </div>
      ) : null}
    </section>
  );
}

function KeywordInputs<T extends typeof defaultNegative | KeywordPayload>({
  value,
  onChange,
  includeCategory = false
}: {
  value: T;
  onChange: (value: T) => void;
  includeCategory?: boolean;
}) {
  return (
    <>
      <label>
        Phrase
        <input
          onChange={(event) => onChange({ ...value, phrase: event.target.value })}
          required
          value={value.phrase}
        />
      </label>
      <label>
        Lang
        <input onChange={(event) => onChange({ ...value, lang: event.target.value })} value={value.lang} />
      </label>
      <label>
        Weight
        <input
          min={1}
          max={10}
          onChange={(event) => onChange({ ...value, weight: Number(event.target.value) })}
          type="number"
          value={value.weight}
        />
      </label>
      {includeCategory && "category" in value ? (
        <label>
          Category
          <input
            onChange={(event) => onChange({ ...value, category: event.target.value })}
            value={value.category}
          />
        </label>
      ) : null}
      <label>
        Regex
        <select
          onChange={(event) => onChange({ ...value, is_regex: event.target.value === "true" })}
          value={String(value.is_regex)}
        >
          <option value="false">false</option>
          <option value="true">true</option>
        </select>
      </label>
    </>
  );
}

function KeywordTable<T extends Keyword | NegativeKeyword>({
  items,
  onToggle,
  onDelete
}: {
  items: T[];
  onToggle: (item: T) => void;
  onDelete: (id: string) => void;
}) {
  if (items.length === 0) {
    return <EmptyState label="Нет записей." />;
  }

  return (
    <table>
      <thead>
        <tr>
          <th>Phrase</th>
          <th>Meta</th>
          <th>Enabled</th>
          <th>Actions</th>
        </tr>
      </thead>
      <tbody>
        {items.map((item) => (
          <tr key={item.id}>
            <td>{item.phrase}</td>
            <td>
              {item.lang} · weight {item.weight} · {item.is_regex ? "regex" : "phrase"}
              {"category" in item ? ` · ${item.category}` : ""}
            </td>
            <td>{item.enabled ? "yes" : "no"}</td>
            <td>
              <div className="actions">
                <button className="secondary" onClick={() => onToggle(item)} type="button">
                  {item.enabled ? "Disable" : "Enable"}
                </button>
                <button className="danger" onClick={() => onDelete(item.id)} type="button">
                  Delete
                </button>
              </div>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
