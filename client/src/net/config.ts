





export type ClientConfig = {
  leaderboard_enabled: boolean;
  queue_enabled: boolean;
  
  leaderboard_disabled_message?: string;
};



const DEFAULT_CONFIG: ClientConfig = {
  leaderboard_enabled: true,
  queue_enabled: false,
};

let cached: ClientConfig = DEFAULT_CONFIG;
let loaded = false;

export async function loadConfig(): Promise<ClientConfig> {
  try {
    const res = await fetch("/api/config", { cache: "no-store" });
    if (!res.ok) {
      cached = DEFAULT_CONFIG;
    } else {
      const body = (await res.json()) as Partial<ClientConfig>;
      cached = {
        leaderboard_enabled: body.leaderboard_enabled ?? true,
        queue_enabled: body.queue_enabled ?? false,
        leaderboard_disabled_message: body.leaderboard_disabled_message,
      };
    }
  } catch {
    cached = DEFAULT_CONFIG;
  }
  loaded = true;
  return cached;
}




export function getConfig(): ClientConfig {
  return cached;
}

export function isConfigLoaded(): boolean {
  return loaded;
}
