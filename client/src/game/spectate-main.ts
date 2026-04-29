import Phaser from "phaser";
import { ROOM_WIDTH, ROOM_HEIGHT } from "./constants";
import { Boot } from "./scenes/Boot";
import { Preloader } from "./scenes/Preloader";
import { GameHUD } from "./scenes/GameHUD";
import { SpectateConnecting } from "./scenes/SpectateConnecting";
import { SpectateGame } from "./scenes/SpectateGame";
import { SpectateEnd } from "./scenes/SpectateEnd";
import { hex, CANVAS_BG } from "./ui/tokens";

export type SpectatorBootArgs = {
  parentId: string;
  playerId: string;
  displayName?: string;
};


export function startSpectator(args: SpectatorBootArgs): Phaser.Game {
  const config: Phaser.Types.Core.GameConfig = {
    type: Phaser.AUTO,
    width: ROOM_WIDTH,
    height: ROOM_HEIGHT,
    parent: args.parentId,
    backgroundColor: hex(CANVAS_BG),
    pixelArt: true,
    roundPixels: true,
    physics: {
      default: "arcade",
      arcade: {
        gravity: { x: 0, y: 0 },
        debug: false,
      },
    },
    scale: {
      mode: Phaser.Scale.FIT,
      autoCenter: Phaser.Scale.CENTER_BOTH,
    },
    scene: [Boot, Preloader, SpectateConnecting, SpectateGame, GameHUD, SpectateEnd],
    callbacks: {
      preBoot: (game) => {
        game.registry.set("nextScene", "SpectateConnecting");
        game.registry.set("spectatorPlayerId", args.playerId);
        game.registry.set("spectatorDisplayName", args.displayName ?? "");
      },
    },
  };

  return new Phaser.Game(config);
}
