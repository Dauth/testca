import Phaser from "phaser";
import { resetSync } from "../net/runContext";
import { CONTROL_BINDINGS } from "./utils/Controls";
import {
  clearCachedPlayerId,
  isTimingsVisible,
  setTimingsVisible,
} from "../prefs";
import {
  ACCENT_PRIMARY,
  DEPTH_HUD_BG,
  DEPTH_HUD_FILL,
  DEPTH_MODAL_TEXT,
  FONT_FAMILY,
  FONT_SIZE_BODY,
  FONT_SIZE_BODY_EM,
  FONT_SIZE_CAPTION,
  FONT_SIZE_HEADING,
  MID_BLUE,
  MIDNIGHT,
  PANEL_FILL,
  TEXT_MUTED,
  TEXT_PRIMARY,
  hex,
} from "../ui/tokens";

type Page = "main" | "controls";

type MainItem = {
  key: "resume" | "toggleTimings" | "controls" | "shop" | "restart" | "logout";
  label(): string;
};

const PANEL_WIDTH = 480;
const PANEL_HEIGHT = 440;



const BLUR_QUALITY = 0;
const BLUR_X = 3;
const BLUR_Y = 3;
const BLUR_STRENGTH = 1;
const BLUR_STEPS = 4;
const BLURRED_SCENES = ["Game", "GameHUD"] as const;


export class PauseMenu extends Phaser.Scene {
  private page: Page = "main";
  private selected = 0;
  private title?: Phaser.GameObjects.Text;
  private hint?: Phaser.GameObjects.Text;
  private body: Phaser.GameObjects.Text[] = [];
  private items: MainItem[] = [];
  private keys?: {
    up: Phaser.Input.Keyboard.Key;
    down: Phaser.Input.Keyboard.Key;
    enter: Phaser.Input.Keyboard.Key;
    esc: Phaser.Input.Keyboard.Key;
  };
  private appliedBlurs: {
    cam: Phaser.Cameras.Scene2D.Camera;
    fx: Phaser.FX.Blur;
  }[] = [];

  constructor() {
    super({ key: "PauseMenu" });
  }

  create(): void {
    const cx = this.scale.width / 2;
    const cy = this.scale.height / 2;

    this.applyCanvasBlur();

    this.items = [
      { key: "resume", label: () => "Close" },
      {
        key: "toggleTimings",
        label: () =>
          isTimingsVisible() ? "Hide Timings" : "Show Timings",
      },
      { key: "controls", label: () => "Controls" },
      { key: "shop", label: () => "Shop" },
      { key: "restart", label: () => "Restart Run" },
      { key: "logout", label: () => "Log Out" },
    ];

    
    this.add
      .rectangle(cx, cy, this.scale.width, this.scale.height, MIDNIGHT, 0.55)
      .setDepth(DEPTH_HUD_BG);

    
    this.add
      .rectangle(cx, cy, PANEL_WIDTH, PANEL_HEIGHT, PANEL_FILL, 0.95)
      .setStrokeStyle(2, MID_BLUE)
      .setDepth(DEPTH_HUD_FILL);

    this.renderPage();

    const kb = this.input.keyboard!;
    this.keys = {
      up: kb.addKey(Phaser.Input.Keyboard.KeyCodes.UP, false),
      down: kb.addKey(Phaser.Input.Keyboard.KeyCodes.DOWN, false),
      enter: kb.addKey(Phaser.Input.Keyboard.KeyCodes.ENTER, false),
      esc: kb.addKey(Phaser.Input.Keyboard.KeyCodes.ESC, false),
    };
    this.keys.up.on("down", () => this.move(-1));
    this.keys.down.on("down", () => this.move(1));
    this.keys.enter.on("down", () => this.activate());
    this.keys.esc.on("down", () => this.back());

    this.events.on("shutdown", this.cleanup, this);
  }

  private renderPage(): void {
    this.title?.destroy();
    this.title = undefined;
    this.hint?.destroy();
    this.hint = undefined;
    for (const t of this.body) t.destroy();
    this.body = [];

    const cx = this.scale.width / 2;
    const cy = this.scale.height / 2;

    if (this.page === "main") {
      this.title = this.add
        .text(cx, cy - 160, "Menu", {
          fontFamily: FONT_FAMILY,
          fontSize: FONT_SIZE_HEADING,
          color: hex(ACCENT_PRIMARY),
        })
        .setOrigin(0.5)
        .setDepth(DEPTH_MODAL_TEXT);

      this.hint = this.add
        .text(
          cx,
          cy + 160,
          "[Up/Down] select   [Enter] confirm   [Esc] close",
          {
            fontFamily: FONT_FAMILY,
            fontSize: FONT_SIZE_CAPTION,
            color: hex(TEXT_MUTED),
          },
        )
        .setOrigin(0.5)
        .setDepth(DEPTH_MODAL_TEXT);

      const startY = cy - 80;
      for (let i = 0; i < this.items.length; i++) {
        const isSel = i === this.selected;
        const label = `${isSel ? "> " : "  "}${this.items[i].label()}`;
        const t = this.add
          .text(cx, startY + i * 36, label, {
            fontFamily: FONT_FAMILY,
            fontSize: FONT_SIZE_BODY_EM,
            color: hex(isSel ? ACCENT_PRIMARY : TEXT_PRIMARY),
          })
          .setOrigin(0.5)
          .setDepth(DEPTH_MODAL_TEXT);
        t.setInteractive({ useHandCursor: true });
        t.on("pointerover", () => {
          if (this.page !== "main") return;
          this.selected = i;
          this.renderPage();
        });
        t.on("pointerdown", () => {
          if (this.page !== "main") return;
          this.selected = i;
          this.activate();
        });
        this.body.push(t);
      }
    } else {
      this.title = this.add
        .text(cx, cy - 160, "Controls", {
          fontFamily: FONT_FAMILY,
          fontSize: FONT_SIZE_HEADING,
          color: hex(ACCENT_PRIMARY),
        })
        .setOrigin(0.5)
        .setDepth(DEPTH_MODAL_TEXT);

      this.hint = this.add
        .text(cx, cy + 160, "[Esc] back", {
          fontFamily: FONT_FAMILY,
          fontSize: FONT_SIZE_CAPTION,
          color: hex(TEXT_MUTED),
        })
        .setOrigin(0.5)
        .setDepth(DEPTH_MODAL_TEXT)
        .setInteractive({ useHandCursor: true });
      this.hint.on("pointerdown", () => this.back());

      const labelX = cx - 160;
      const valueX = cx + 160;
      const startY = cy - 110;
      const rowGap = 26;
      for (let i = 0; i < CONTROL_BINDINGS.length; i++) {
        const [name, key] = CONTROL_BINDINGS[i];
        const t1 = this.add
          .text(labelX, startY + i * rowGap, name, {
            fontFamily: FONT_FAMILY,
            fontSize: FONT_SIZE_BODY,
            color: hex(TEXT_PRIMARY),
          })
          .setOrigin(0, 0)
          .setDepth(DEPTH_MODAL_TEXT);
        const t2 = this.add
          .text(valueX, startY + i * rowGap, key, {
            fontFamily: FONT_FAMILY,
            fontSize: FONT_SIZE_BODY,
            color: hex(ACCENT_PRIMARY),
          })
          .setOrigin(1, 0)
          .setDepth(DEPTH_MODAL_TEXT);
        this.body.push(t1, t2);
      }
    }
  }

  private move(delta: number): void {
    if (this.page !== "main") return;
    this.selected =
      (this.selected + delta + this.items.length) % this.items.length;
    this.renderPage();
  }

  private activate(): void {
    if (this.page !== "main") return;
    const item = this.items[this.selected];
    switch (item.key) {
      case "resume":
        this.close();
        return;
      case "toggleTimings": {
        const next = !isTimingsVisible();
        setTimingsVisible(next);
        
        this.game.events.emit("timingsVisibilityChanged", next);
        
        this.renderPage();
        return;
      }
      case "controls":
        this.page = "controls";
        this.renderPage();
        return;
      case "shop":
        this.removeCanvasBlur();
        this.scene.launch("ShopMenu");
        this.scene.stop();
        return;
      case "restart":
        this.restart();
        return;
      case "logout":
        this.logout();
        return;
    }
  }

  private back(): void {
    if (this.page === "controls") {
      this.page = "main";
      this.renderPage();
      return;
    }
    this.close();
  }

  private close(): void {
    this.removeCanvasBlur();
    this.scene.resume("Game");
    this.scene.stop();
  }

  private restart(): void {
    
    
    
    
    
    
    
    
    
    this.removeCanvasBlur();
    this.scene.stop("Game");
    this.scene.stop("GameHUD");
    this.scene.stop("WinScreen");
    resetSync();
    this.scene.start("MainMenu");
  }

  private logout(): void {
    
    
    clearCachedPlayerId();
    this.restart();
  }

  private applyCanvasBlur(): void {
    for (const key of BLURRED_SCENES) {
      const target = this.scene.get(key);
      const cam = target?.cameras?.main;
      if (!cam || !cam.postFX) continue;
      const fx = cam.postFX.addBlur(
        BLUR_QUALITY,
        BLUR_X,
        BLUR_Y,
        BLUR_STRENGTH,
        0xffffff,
        BLUR_STEPS,
      );
      this.appliedBlurs.push({ cam, fx });
    }
  }

  private removeCanvasBlur(): void {
    for (const { cam, fx } of this.appliedBlurs) {
      
      
      
      try {
        cam.postFX?.remove(fx);
      } catch {
        
      }
    }
    this.appliedBlurs = [];
  }

  private cleanup(): void {
    this.title?.destroy();
    this.title = undefined;
    this.hint?.destroy();
    this.hint = undefined;
    for (const t of this.body) t.destroy();
    this.body = [];

    if (this.keys) {
      this.keys.up.removeAllListeners();
      this.keys.down.removeAllListeners();
      this.keys.enter.removeAllListeners();
      this.keys.esc.removeAllListeners();
      this.keys = undefined;
    }
    
    
    this.removeCanvasBlur();
  }
}

export default PauseMenu;
