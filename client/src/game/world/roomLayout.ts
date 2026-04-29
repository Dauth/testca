import Phaser from "phaser";

import type { RoomData } from "../../net/packet";
import { ROOM_HEIGHT, ROOM_WIDTH } from "../constants";
import { Enemy } from "../entities/Enemy";
import { Pickup } from "../entities/Pickup";
import {
  DEPTH_BADGE,
  DEPTH_BG_FALLBACK,
  DEPTH_TILEMAP,
  DEPTH_WALL_FALLBACK,
  FONT_FAMILY,
  FONT_SIZE_MICRO,
  hex,
  TEXT_PRIMARY,
} from "../ui/tokens";


export type DoorRef = {
  doorId: number;
  x: number;
  y: number;
  targetRoom: number;
  tileX: number;
  tileY: number;
  unlockedGid: number;
};

export type RoomObjects = {
  enemies: Map<number, Enemy>;
  pickups: Map<number, Pickup>;
  doors: Map<number, DoorRef>;
};


export type PaintedBackground = {
  created: Phaser.GameObjects.GameObject[];
  wallsLayer?: Phaser.Tilemaps.TilemapLayer;
};

export type BuiltRoom = RoomObjects;





const ROOM_TINTS: number[] = [
  0x1a2338, 
  0x16213e, 
  0x0f3460, 
  0x2d2d44, 
  0x3b2417, 
  0x1f4529, 
  0x402020, 
  0x254741, 
  0x3a1f5c, 
  0x202020, 
  0x502020, 
];

const WALL_COLOR = 0x0a0a0a;
const WALL_THICKNESS = 16;

function tintForRoom(data: RoomData): number {
  const match = /(\d+)/.exec(data.tilemap_id);
  if (match) {
    const n = parseInt(match[1], 10);
    if (Number.isFinite(n) && n >= 0) {
      return ROOM_TINTS[n % ROOM_TINTS.length];
    }
  }
  return ROOM_TINTS[data.room_index % ROOM_TINTS.length];
}


export function clearRoom(objs: RoomObjects): void {
  objs.enemies.forEach((e) => e.destroy());
  objs.enemies.clear();
  objs.pickups.forEach((p) => p.destroy());
  objs.pickups.clear();
  objs.doors.clear();
}


export function paintRoomBackground(
  scene: Phaser.Scene,
  data: RoomData,
): PaintedBackground {
  const created: Phaser.GameObjects.GameObject[] = [];
  let wallsLayer: Phaser.Tilemaps.TilemapLayer | undefined;

  if (scene.cache.tilemap.exists(data.tilemap_id)) {
    try {
      const map = scene.make.tilemap({ key: data.tilemap_id });
      const tilesetNames = map.tilesets.map((t) => t.name);
      if (tilesetNames.length > 0) {
        const textureKey = scene.textures.exists("tilemap")
          ? "tilemap"
          : tilesetNames[0];
        const tileset = map.addTilesetImage(tilesetNames[0], textureKey);
        if (tileset) {
          for (const layerData of map.layers) {
            const layer = map.createLayer(layerData.name, tileset, 0, 0);
            if (layer) {
              layer.setDepth(DEPTH_TILEMAP);
              created.push(layer);
              if (layerData.name === "Walls") {
                wallsLayer = layer;
              }
            }
          }
          return { created, wallsLayer };
        }
      }
    } catch {
      
    }
  }

  const tint = tintForRoom(data);

  const bg = scene.add.rectangle(
    ROOM_WIDTH / 2,
    ROOM_HEIGHT / 2,
    ROOM_WIDTH,
    ROOM_HEIGHT,
    tint,
  );
  bg.setDepth(DEPTH_BG_FALLBACK);
  created.push(bg);

  const top = scene.add.rectangle(
    ROOM_WIDTH / 2,
    WALL_THICKNESS / 2,
    ROOM_WIDTH,
    WALL_THICKNESS,
    WALL_COLOR,
  );
  const bottom = scene.add.rectangle(
    ROOM_WIDTH / 2,
    ROOM_HEIGHT - WALL_THICKNESS / 2,
    ROOM_WIDTH,
    WALL_THICKNESS,
    WALL_COLOR,
  );
  const left = scene.add.rectangle(
    WALL_THICKNESS / 2,
    ROOM_HEIGHT / 2,
    WALL_THICKNESS,
    ROOM_HEIGHT,
    WALL_COLOR,
  );
  const right = scene.add.rectangle(
    ROOM_WIDTH - WALL_THICKNESS / 2,
    ROOM_HEIGHT / 2,
    WALL_THICKNESS,
    ROOM_HEIGHT,
    WALL_COLOR,
  );
  for (const w of [top, bottom, left, right]) {
    w.setDepth(DEPTH_WALL_FALLBACK);
    created.push(w);
  }

  
  const label = scene.add.text(
    ROOM_WIDTH - WALL_THICKNESS - 8,
    WALL_THICKNESS + 6,
    data.tilemap_id,
    {
      fontFamily: FONT_FAMILY,
      fontSize: FONT_SIZE_MICRO,
      color: hex(TEXT_PRIMARY),
    },
  );
  label.setAlpha(0.35);
  label.setOrigin(1, 0);
  label.setDepth(DEPTH_BADGE);
  created.push(label);

  return { created, wallsLayer: undefined };
}


export function buildRoom(scene: Phaser.Scene, data: RoomData): RoomObjects {
  const enemies = new Map<number, Enemy>();
  const pickups = new Map<number, Pickup>();
  const doors = new Map<number, DoorRef>();

  for (const spawn of data.enemies) {
    const enemy = new Enemy(scene, {
      entity_id: spawn.entity_id,
      type: spawn.type,
      x: spawn.x,
      y: spawn.y,
      hp: spawn.hp,
      state: 0,
    });
    enemies.set(enemy.entityId, enemy);
  }

  for (const spawn of data.pickups) {
    const pickup = new Pickup(scene, spawn);
    pickups.set(pickup.entityId, pickup);
  }

  for (const def of data.doors) {
    doors.set(def.door_id, {
      doorId: def.door_id,
      x: def.x,
      y: def.y,
      targetRoom: def.target_room,
      tileX: def.tile_x,
      tileY: def.tile_y,
      unlockedGid: def.unlocked_gid,
    });
  }

  return { enemies, pickups, doors };
}
