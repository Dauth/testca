import type { SplitData } from "../net/packet";



const PB_KEY_PREFIX = "vibecat:pb:";
const TIMINGS_KEY = "vibecat:timings-visible";
const PLAYER_ID_KEY = "vibecat:player-id";

type StoredPB = {
  total_ms: number;
  splits: SplitData[];
};

function safeGet(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function safeSet(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    
  }
}

function currentPBKey(): string | null {
  const playerId = getCachedPlayerId();
  return playerId ? `${PB_KEY_PREFIX}${playerId}` : null;
}

export function getStoredPB(): StoredPB | null {
  const key = currentPBKey();
  if (!key) return null;
  const raw = safeGet(key);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as StoredPB;
    if (typeof parsed?.total_ms !== "number" || !Array.isArray(parsed.splits)) {
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}


export function maybeRecordPB(totalMs: number, splits: SplitData[]): boolean {
  const key = currentPBKey();
  if (!key) return false;
  const current = getStoredPB();
  if (current && current.total_ms <= totalMs) return false;
  const next: StoredPB = { total_ms: totalMs, splits: splits.slice() };
  safeSet(key, JSON.stringify(next));
  return true;
}

export function isTimingsVisible(): boolean {
  
  
  
  const raw = safeGet(TIMINGS_KEY);
  if (raw === "0") return false;
  return true;
}

export function setTimingsVisible(visible: boolean): void {
  safeSet(TIMINGS_KEY, visible ? "1" : "0");
}

export function setCachedPlayerId(playerId: string): void {
  if (!playerId) return;
  safeSet(PLAYER_ID_KEY, playerId);
}

export function getCachedPlayerId(): string | null {
  return safeGet(PLAYER_ID_KEY);
}

export function clearCachedPlayerId(): void {
  try {
    localStorage.removeItem(PLAYER_ID_KEY);
  } catch {
    
  }
}
