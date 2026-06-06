import { useEffect, useMemo, useRef, useState } from "react";
import type { UserListItem } from "../types";

const SAMPLE_SIZE = 10;

function formatSubtitle(user: UserListItem): string {
  const parts = [user.city, `${user.order_count} 单`, `${user.voucher_count} 券`];
  if (user.highlight_order) parts.push(user.highlight_order);
  return parts.join(" · ");
}

export function DemoUserSwitcher({
  users,
  totalUsers,
  value,
  onChange,
  onReshuffle,
  disabled,
  reshuffling,
}: {
  users: UserListItem[];
  totalUsers: number;
  value: string;
  onChange: (userId: string) => void;
  onReshuffle: () => void;
  disabled?: boolean;
  reshuffling?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const rootRef = useRef<HTMLDivElement>(null);
  const current = users.find((item) => item.id === value);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return users;
    return users.filter(
      (user) =>
        user.id.toLowerCase().includes(q) ||
        user.display_name.toLowerCase().includes(q) ||
        user.city.toLowerCase().includes(q) ||
        user.membership_level.toLowerCase().includes(q) ||
        (user.highlight_order ?? "").toLowerCase().includes(q) ||
        (user.phone_mask ?? "").includes(q)
    );
  }, [query, users]);

  useEffect(() => {
    if (!open) return;
    function onDocClick(event: MouseEvent) {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [open]);

  function pick(userId: string) {
    onChange(userId);
    setOpen(false);
    setQuery("");
  }

  const poolLabel =
    totalUsers > users.length
      ? `库内 ${totalUsers} 人 · 随机 ${users.length}`
      : `共 ${totalUsers} 人`;

  return (
    <div ref={rootRef} className="relative mt-2">
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-left transition hover:border-[#fe2c55]/30 hover:bg-white disabled:opacity-50"
      >
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[#fe2c55]/10 text-xs font-bold text-[#fe2c55]">
          {current?.display_name?.slice(0, 1) ?? "?"}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-semibold text-slate-900">
            {current?.display_name ?? "选择用户"}
          </span>
          <span className="block truncate text-[11px] text-slate-500">
            {current ? formatSubtitle(current) : poolLabel}
          </span>
        </span>
        <span className="shrink-0 text-[10px] font-medium text-slate-400">
          {poolLabel} {open ? "▴" : "▾"}
        </span>
      </button>

      {open && (
        <div className="absolute left-0 right-0 top-[calc(100%+6px)] z-30 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-lg">
          <div className="border-b border-slate-100 p-2">
            <input
              type="search"
              autoFocus
              value={query}
              disabled={disabled}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="在本批用户中搜索…"
              className="w-full rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1.5 text-xs text-slate-800 outline-none placeholder:text-slate-400 focus:border-[#fe2c55]/40 focus:bg-white"
            />
            <div className="mt-1.5 flex items-center justify-between gap-2 px-0.5 text-[10px] text-slate-400">
              <span>
                {query
                  ? `匹配 ${filtered.length} / ${users.length}`
                  : `从 ${totalUsers} 位用户中随机展示 ${users.length} 位`}
              </span>
              <button
                type="button"
                disabled={disabled || reshuffling || totalUsers <= 1}
                onClick={() => onReshuffle()}
                className="shrink-0 font-medium text-[#fe2c55] disabled:opacity-40"
              >
                {reshuffling ? "换批中…" : "换一批"}
              </button>
            </div>
          </div>

          <ul className="max-h-56 overflow-y-auto overscroll-contain py-1">
            {filtered.length === 0 ? (
              <li className="px-3 py-4 text-center text-xs text-slate-400">没有匹配的用户</li>
            ) : (
              filtered.map((user) => {
                const selected = user.id === value;
                return (
                  <li key={user.id}>
                    <button
                      type="button"
                      disabled={disabled}
                      onClick={() => pick(user.id)}
                      className={`flex w-full items-start gap-2 px-3 py-2 text-left transition ${
                        selected ? "bg-[#fff1f3]" : "hover:bg-slate-50"
                      }`}
                    >
                      <span
                        className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[11px] font-bold ${
                          selected ? "bg-[#fe2c55] text-white" : "bg-slate-100 text-slate-600"
                        }`}
                      >
                        {user.display_name.slice(0, 1)}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span
                          className={`block truncate text-sm ${
                            selected ? "font-semibold text-[#fe2c55]" : "font-medium text-slate-800"
                          }`}
                        >
                          {user.display_name}
                        </span>
                        <span className="block truncate text-[11px] text-slate-500">{formatSubtitle(user)}</span>
                        <span className="block truncate text-[10px] text-slate-400">
                          {user.membership_level} · {user.id}
                        </span>
                      </span>
                    </button>
                  </li>
                );
              })
            )}
          </ul>
        </div>
      )}
    </div>
  );
}

export { SAMPLE_SIZE };
