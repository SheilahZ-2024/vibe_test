import type { EdgeContext } from "../types";
import { USER_ID_STORAGE_KEY } from "./userSession";

const FOCUS_ORDER_PREFIX = "douyin-life-focus-order";

function focusKey(userId: string) {
  return `${FOCUS_ORDER_PREFIX}:${userId}`;
}

export function getStoredFocusOrderId(userId?: string): string | null {
  if (typeof window === "undefined") return null;
  const uid = userId ?? localStorage.getItem(USER_ID_STORAGE_KEY);
  if (!uid) return localStorage.getItem(FOCUS_ORDER_PREFIX);
  return localStorage.getItem(focusKey(uid));
}

export function setStoredFocusOrderId(orderId: string | null, userId?: string): void {
  const uid = userId ?? localStorage.getItem(USER_ID_STORAGE_KEY);
  const key = uid ? focusKey(uid) : FOCUS_ORDER_PREFIX;
  if (orderId) localStorage.setItem(key, orderId);
  else localStorage.removeItem(key);
}

export function clearFocusForUser(userId: string): void {
  localStorage.removeItem(focusKey(userId));
}

export function resolveFocusOrderId(stored: string | null, orderIds: string[]): string | null {
  if (stored && orderIds.includes(stored)) return stored;
  if (orderIds.length === 1) return orderIds[0];
  return null;
}

export function withFocusOrder(edge: EdgeContext, focusOrderId: string | null): EdgeContext {
  return {
    ...edge,
    focus_order_id: focusOrderId,
    packet_size_bytes: new Blob([JSON.stringify({ ...edge, focus_order_id: focusOrderId })]).size,
  };
}
