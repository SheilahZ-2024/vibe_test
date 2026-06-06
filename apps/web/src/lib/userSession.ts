export const USER_ID_STORAGE_KEY = "douyin-life-user-id";

export const DEFAULT_USER_ID = "user_001";

export function getStoredUserId(): string {
  if (typeof window === "undefined") return DEFAULT_USER_ID;
  return localStorage.getItem(USER_ID_STORAGE_KEY) || DEFAULT_USER_ID;
}

export function setStoredUserId(userId: string): void {
  localStorage.setItem(USER_ID_STORAGE_KEY, userId);
}

export function resolveUserId(storedId: string, availableIds: string[]): string {
  if (availableIds.includes(storedId)) return storedId;
  if (availableIds.includes(DEFAULT_USER_ID)) return DEFAULT_USER_ID;
  return availableIds[0] ?? DEFAULT_USER_ID;
}
