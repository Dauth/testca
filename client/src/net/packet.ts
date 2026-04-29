export const C2SType = {
  AUTH: 0x01,
  START_RUN: 0x02,
  INPUT: 0x03,
  SHOOT: 0x04,
  SWITCH_WEAPON: 0x05,
  INTERACT: 0x06,
  ENTER_DOOR: 0x07,
  SHOP_PURCHASE: 0x09,
  
  
  REPLAY_CONTROL: 0x0a,
} as const;
export type C2SType = (typeof C2SType)[keyof typeof C2SType];

export type ReplayControlAction = "play" | "pause" | "set_speed" | "restart";

export const S2CType = {
  AUTH_OK: 0x81,
  RUN_STARTED: 0x82,
  STATE: 0x83,
  ROOM_LOAD: 0x84,
  RUN_COMPLETE: 0x85,
  LEADERBOARD: 0x86,
  ERROR: 0x87,
  DOOR_UNLOCKED: 0x88,
  ENTITY_DIED: 0x89,
} as const;
export type S2CType = (typeof S2CType)[keyof typeof S2CType];

export type C2SEnvelope<T extends C2SType = C2SType> = {
  type: T; 
  seq: number; 
  ts: number; 
  data: C2SDataFor<T>;
};

export type S2CEnvelope<T extends S2CType = S2CType> = {
  type: T; 
  seq: number; 
  server_ts: number; 
  data: S2CDataFor<T>;
};

export type C2SDataFor<T extends C2SType> = T extends typeof C2SType.AUTH
  ? { player_id: string } 
  : T extends typeof C2SType.START_RUN
    ? { start_time: number } 
    : T extends typeof C2SType.INPUT
      ? { dx: number; dy: number } 
      : T extends typeof C2SType.SHOOT
        ? { aim_angle: number } 
        : T extends typeof C2SType.SWITCH_WEAPON
          ? { weapon_id: number } 
          : T extends typeof C2SType.INTERACT
            ? { target_id: number; claimed_type: number } 
            : T extends typeof C2SType.ENTER_DOOR
              ? { door_id: number }
              : T extends typeof C2SType.SHOP_PURCHASE
                ? { item_id: number } 
                : T extends typeof C2SType.REPLAY_CONTROL
                  ? { action: ReplayControlAction; speed?: number }
                  : never;

export type S2CDataFor<T extends S2CType> = T extends typeof S2CType.AUTH_OK
  ? { display_name: string }
  : T extends typeof S2CType.RUN_STARTED
    ? { seed: number; room: RoomData; display_name?: string }
    : T extends typeof S2CType.STATE
      ? {
          elapsed_ms: number;
          player: PlayerSnapshot;
          entities: EntitySnapshot[];
          projectiles: ProjSnapshot[];
          pickups: PickupSpawn[];
        }
      : T extends typeof S2CType.ROOM_LOAD
        ? { room_index: number; room: RoomData; split_ms: number }
        : T extends typeof S2CType.RUN_COMPLETE
          ? {
              outcome: RunOutcome;
              total_ms: number;
              rank: number;
              splits: SplitData[];
              replay_id?: string;
              seed?: number;
            }
          : T extends typeof S2CType.LEADERBOARD
            ? { entries: LeaderboardEntry[] }
            : T extends typeof S2CType.ERROR
              ? { code: string; message: string }
              : T extends typeof S2CType.DOOR_UNLOCKED
                ? { door_id: number }
                : T extends typeof S2CType.ENTITY_DIED
                  ? { entity_id: number }
                  : never;

export type RoomData = {
  room_index: number; 
  tilemap_id: string; 
  enemies: EnemySpawn[];
  pickups: PickupSpawn[];
  doors: DoorDef[];
};

export type EnemySpawn = {
  entity_id: number;
  type: number;
  x: number;
  y: number;
  hp: number;
};
export type PickupSpawn = {
  entity_id: number;
  type: number;
  x: number;
  y: number;
};
export type DoorDef = {
  door_id: number;
  x: number;
  y: number;
  target_room: number;
  locked: boolean;
  
  tile_x: number;
  tile_y: number;
  unlocked_gid: number;
};

export type PlayerSnapshot = {
  x: number;
  y: number;
  hp: number; 
  weapon_id: number; 
  ammo: number;
  coins: number; 
  speed_stacks: number; 
  fire_rate_stacks: number; 
  damage_stacks: number; 
  aim_angle?: number; 
};

export type EntitySnapshot = {
  entity_id: number;
  type: number;
  x: number;
  y: number;
  hp: number;
  state: number; 
};

export type ProjSnapshot = {
  proj_id: number;
  x: number;
  y: number;
  angle: number;
  owner: number; 
};

export type SplitData = { room_index: number; time_ms: number; kills: number };




export const RunOutcome = {
  COMPLETED: "completed",
  FAILED: "failed",
} as const;
export type RunOutcome = (typeof RunOutcome)[keyof typeof RunOutcome];

export type LeaderboardEntry = {
  rank: number;
  display_name: string;
  total_ms: number;
  splits: SplitData[];
  seed: number;
  replay_id: string;
  submitted_at: string;
};
