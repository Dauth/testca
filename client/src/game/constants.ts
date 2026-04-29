export const ROOM_WIDTH = 1280;
export const ROOM_HEIGHT = 768;
export const ROOM_COUNT = 10;
export const WIN_ROOM = 10;

export const PLAYER_MAX_HEALTH = 100;

export const WS_URL = (() => {
  if (typeof window !== "undefined" && window.location) {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    
    
    const override = import.meta.env?.VITE_WS_URL as string | undefined;
    if (override) return override;
    return `${proto}//${window.location.host}/ws`;
  }
  return "ws://localhost:8080/ws";
})();


export const INPUT_SEND_INTERVAL_MS = 50;







export const HOLD_FIRE_RATE_MULT = 0.85;

export const WALK_ANIM_FRAMERATE = 8;
