import Phaser from "phaser";
import { ROOM_WIDTH, ROOM_HEIGHT } from "./constants";
import { Boot } from "./scenes/Boot";
import { Preloader } from "./scenes/Preloader";
import { GameHUD } from "./scenes/GameHUD";
import { ReplayConnecting } from "./scenes/ReplayConnecting";
import { ReplayGame } from "./scenes/ReplayGame";
import { ReplayControls } from "./scenes/ReplayControls";
import { ReplayEnd } from "./scenes/ReplayEnd";
import { hex, CANVAS_BG } from "./ui/tokens";

export type ReplayBootArgs = {
  parentId: string;
  replayId: string;
};


export function startReplay(args: ReplayBootArgs): Phaser.Game {
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
    scene: [
      Boot,
      Preloader,
      ReplayConnecting,
      ReplayGame,
      GameHUD,
      ReplayControls,
      ReplayEnd,
    ],
    callbacks: {
      preBoot: (game) => {
        game.registry.set("nextScene", "ReplayConnecting");
        game.registry.set("replayId", args.replayId);
      },
    },
  };

  return new Phaser.Game(config);
}
