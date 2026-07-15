export function LoadingState({ label = "Загрузка..." }: { label?: string }) {
  return <div className="state loading">{label}</div>;
}

export function EmptyState({ label }: { label: string }) {
  return <div className="state empty">{label}</div>;
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="state error">
      <p>{message}</p>
      {onRetry ? (
        <button className="secondary" onClick={onRetry} type="button">
          Повторить
        </button>
      ) : null}
    </div>
  );
}

export function StatusBadge({ value }: { value: string }) {
  return <span className={`badge badge-${value}`}>{value}</span>;
}
