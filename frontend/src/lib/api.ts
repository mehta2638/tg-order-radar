import type {
  Favorite,
  Keyword,
  KeywordPayload,
  NegativeKeyword,
  Order,
  OrderFilters,
  OrderListResponse,
  OrderStatus,
  Source,
  SourceListResponse,
  StatsSummary,
  Subscription,
  SubscriptionPayload
} from "@/lib/types";

const DEFAULT_API_BASE_URL = "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly code?: string
  ) {
    super(message);
  }
}

export interface ApiSession {
  apiBaseUrl: string;
  apiKey: string;
}

export class ApiClient {
  constructor(private readonly session: ApiSession) {}

  async getOrders(filters: OrderFilters): Promise<OrderListResponse> {
    return this.request<OrderListResponse>(`/api/v1/orders${queryString(filters)}`);
  }

  async updateOrderStatus(order: Order, status: OrderStatus): Promise<Order> {
    return this.request<Order>(`/api/v1/orders/${order.id}/status`, {
      method: "PATCH",
      body: JSON.stringify({ status, version: order.version })
    });
  }

  async exportOrdersCsv(filters: OrderFilters & { limit?: number }): Promise<string> {
    return this.requestText(`/api/v1/orders/export${queryString({ ...filters, format: "csv" })}`);
  }

  async getFavorites(): Promise<{ items: Favorite[]; total: number }> {
    return this.request<{ items: Favorite[]; total: number }>("/api/v1/favorites");
  }

  async addFavorite(orderId: string): Promise<Favorite> {
    return this.request<Favorite>(`/api/v1/favorites/${orderId}`, { method: "POST" });
  }

  async removeFavorite(orderId: string): Promise<void> {
    await this.request<void>(`/api/v1/favorites/${orderId}`, { method: "DELETE" });
  }

  async getSources(params: { q?: string; page?: number; size?: number }): Promise<SourceListResponse> {
    return this.request<SourceListResponse>(`/api/v1/sources${queryString(params)}`);
  }

  async createSource(link: string): Promise<Source> {
    return this.request<Source>("/api/v1/sources", {
      method: "POST",
      body: JSON.stringify({ link })
    });
  }

  async updateSource(sourceId: string, enabled: boolean): Promise<Source> {
    return this.request<Source>(`/api/v1/sources/${sourceId}`, {
      method: "PATCH",
      body: JSON.stringify({ enabled })
    });
  }

  async deleteSource(sourceId: string): Promise<void> {
    await this.request<void>(`/api/v1/sources/${sourceId}`, { method: "DELETE" });
  }

  async validateSource(sourceId: string): Promise<Source> {
    return this.request<Source>(`/api/v1/sources/${sourceId}/validate`, { method: "POST" });
  }

  async getKeywords(): Promise<{ items: Keyword[]; total: number }> {
    return this.request<{ items: Keyword[]; total: number }>("/api/v1/keywords");
  }

  async createKeyword(payload: KeywordPayload): Promise<Keyword> {
    return this.request<Keyword>("/api/v1/keywords", {
      method: "POST",
      body: JSON.stringify(payload)
    });
  }

  async updateKeyword(keywordId: string, payload: Partial<KeywordPayload>): Promise<Keyword> {
    return this.request<Keyword>(`/api/v1/keywords/${keywordId}`, {
      method: "PATCH",
      body: JSON.stringify(payload)
    });
  }

  async deleteKeyword(keywordId: string): Promise<void> {
    await this.request<void>(`/api/v1/keywords/${keywordId}`, { method: "DELETE" });
  }

  async getNegativeKeywords(): Promise<{ items: NegativeKeyword[]; total: number }> {
    return this.request<{ items: NegativeKeyword[]; total: number }>("/api/v1/negative-keywords");
  }

  async createNegativeKeyword(payload: Omit<KeywordPayload, "category">): Promise<NegativeKeyword> {
    return this.request<NegativeKeyword>("/api/v1/negative-keywords", {
      method: "POST",
      body: JSON.stringify(payload)
    });
  }

  async updateNegativeKeyword(
    keywordId: string,
    payload: Partial<Omit<KeywordPayload, "category">>
  ): Promise<NegativeKeyword> {
    return this.request<NegativeKeyword>(`/api/v1/negative-keywords/${keywordId}`, {
      method: "PATCH",
      body: JSON.stringify(payload)
    });
  }

  async deleteNegativeKeyword(keywordId: string): Promise<void> {
    await this.request<void>(`/api/v1/negative-keywords/${keywordId}`, { method: "DELETE" });
  }

  async getStatsSummary(): Promise<StatsSummary> {
    return this.request<StatsSummary>("/api/v1/stats/summary");
  }

  async getSubscriptions(params?: { user_id?: string; all_users?: boolean }): Promise<{
    items: Subscription[];
    total: number;
  }> {
    return this.request<{ items: Subscription[]; total: number }>(
      `/api/v1/subscriptions${queryString(params ?? {})}`
    );
  }

  async getSubscription(subscriptionId: string): Promise<Subscription> {
    return this.request<Subscription>(`/api/v1/subscriptions/${subscriptionId}`);
  }

  async createSubscription(payload: SubscriptionPayload): Promise<Subscription> {
    return this.request<Subscription>("/api/v1/subscriptions", {
      method: "POST",
      body: JSON.stringify(payload)
    });
  }

  async updateSubscription(
    subscriptionId: string,
    payload: Partial<SubscriptionPayload>
  ): Promise<Subscription> {
    return this.request<Subscription>(`/api/v1/subscriptions/${subscriptionId}`, {
      method: "PATCH",
      body: JSON.stringify(payload)
    });
  }

  async deleteSubscription(subscriptionId: string): Promise<void> {
    await this.request<void>(`/api/v1/subscriptions/${subscriptionId}`, { method: "DELETE" });
  }

  async enableSubscription(subscriptionId: string): Promise<Subscription> {
    return this.request<Subscription>(`/api/v1/subscriptions/${subscriptionId}/enable`, {
      method: "POST"
    });
  }

  async disableSubscription(subscriptionId: string): Promise<Subscription> {
    return this.request<Subscription>(`/api/v1/subscriptions/${subscriptionId}/disable`, {
      method: "POST"
    });
  }

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const response = await fetch(`${this.session.apiBaseUrl}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        "X-API-Key": this.session.apiKey,
        ...init.headers
      }
    });

    if (response.status === 204) {
      return undefined as T;
    }

    const contentType = response.headers.get("content-type") ?? "";
    const payload = contentType.includes("application/json") ? await response.json() : null;

    if (!response.ok) {
      const error = payload?.error;
      throw new ApiError(error?.message ?? `API request failed with ${response.status}`, response.status, error?.code);
    }

    return payload as T;
  }

  private async requestText(path: string, init: RequestInit = {}): Promise<string> {
    const response = await fetch(`${this.session.apiBaseUrl}${path}`, {
      ...init,
      headers: {
        "X-API-Key": this.session.apiKey,
        ...init.headers
      }
    });

    if (!response.ok) {
      const contentType = response.headers.get("content-type") ?? "";
      const payload = contentType.includes("application/json") ? await response.json() : null;
      const error = payload?.error;
      throw new ApiError(error?.message ?? `API request failed with ${response.status}`, response.status, error?.code);
    }

    return response.text();
  }
}

export function getDefaultApiBaseUrl(): string {
  return process.env.NEXT_PUBLIC_API_BASE_URL ?? DEFAULT_API_BASE_URL;
}

function queryString(params: object): string {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (
      (typeof value === "string" || typeof value === "number" || typeof value === "boolean") &&
      value !== ""
    ) {
      search.set(key, String(value));
    }
  });
  const value = search.toString();
  return value ? `?${value}` : "";
}
