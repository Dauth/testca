import Phaser from "phaser";
import { getSync, resetSync } from "../net/runContext";
import { CONTROL_BINDINGS } from "./utils/Controls";
import {
  clearCachedPlayerId,
  getCachedPlayerId,
  setCachedPlayerId,
} from "../prefs";
import { WS_URL } from "../constants";
import { getConfig } from "../../net/config";
import {
  ACCENT_PRIMARY,
  BUTTON_HOVER_COLOR,
  DEEP_NAVY,
  DEPTH_SPLASH,
  FONT_FAMILY,
  FONT_SIZE_BODY,
  FONT_SIZE_CAPTION,
  FONT_SIZE_SMALL,
  MID_BLUE,
  TEXT_DIM,
  TEXT_MUTED,
  TEXT_PRIMARY,
  hex,
} from "../ui/tokens";


interface SponsorSpec {
  readonly label: string;
  readonly placeholder: string;
  readonly url: string;
  readonly imageSrc?: string;
}

const SPONSORS: ReadonlyArray<SponsorSpec> = [
  {
    label: "HTX",
    placeholder: "×",
    url: "https://www.htx.gov.sg/",
    imageSrc: "assets/htx_logo.png",
  },
  {
    label: "Niklaus",
    placeholder: "N",
    url: "",
    imageSrc: "assets/niklas_logo.png",
  },
  {
    label: "OtterSec",
    placeholder: "◉",
    url: "https://osec.io/",
    imageSrc: "assets/ottersec_logo.png",
  },
];


export class MainMenu extends Phaser.Scene {
  private usernameInput?: HTMLInputElement;
  private passwordInput?: HTMLInputElement;
  private statusDot?: Phaser.GameObjects.Arc;
  private statusText?: Phaser.GameObjects.Text;
  private clockSkewText?: Phaser.GameObjects.Text;
  private startButton?: HTMLButtonElement;
  private submitting = false;
  private resizeHandlers: Array<() => void> = [];
  private sponsorLogoEls: HTMLImageElement[] = [];
  private sponsorHoverRects: Phaser.GameObjects.Rectangle[] = [];
  private controlsTexts: Phaser.GameObjects.Text[] = [];
  private loginTexts: Phaser.GameObjects.Text[] = [];
  private readyTexts: Phaser.GameObjects.GameObject[] = [];
  private readyEnterKey?: Phaser.Input.Keyboard.Key;
  private readyActive = false;

  
  
  
  private static readonly CLOCK_SKEW_WARN_MS = 1500;
  private static readonly IDLE_STATUS_COLOR = 0x342e37;
  private static readonly WARNING_STATUS_COLOR = 0x4a5e88;
  private static readonly SUCCESS_STATUS_COLOR = 0x2f7d32;
  private static readonly ERROR_STATUS_COLOR = 0x7a2430;

  private static readonly PANEL_WIDTH = 460;
  private static readonly PANEL_MIN_WIDTH = 340;
  private static readonly PANEL_HEIGHT = 200;
  private static readonly PANEL_MARGIN = 40;
  private static readonly PANEL_PADDING = 20;
  
  
  private static readonly LABEL_COLUMN_WIDTH = 110;
  private static readonly LABEL_GAP = 8;
  private static readonly SPONSOR_PANEL_HEIGHT = 140;
  private static readonly SPONSOR_PANEL_GAP = 12;
  private static readonly SPONSOR_CARD_HEIGHT = 92;
  private static readonly SPONSOR_CARD_GAP = 10;
  private getPanelLayout() {
    const margin = Math.min(MainMenu.PANEL_MARGIN, Math.max(16, this.scale.width * 0.05));
    const panelWidth = Phaser.Math.Clamp(
      this.scale.width - margin * 2,
      MainMenu.PANEL_MIN_WIDTH,
      MainMenu.PANEL_WIDTH,
    );
    const inputWidth = panelWidth - MainMenu.PANEL_PADDING * 2;
    const labelColumnWidth = panelWidth < 400 ? 92 : MainMenu.LABEL_COLUMN_WIDTH;
    const rowInputWidth = inputWidth - labelColumnWidth - MainMenu.LABEL_GAP;
    const panelX = this.scale.width - panelWidth - margin;
    const stackBottom = this.scale.height - margin;
    const sponsorTop = stackBottom - MainMenu.SPONSOR_PANEL_HEIGHT;
    const loginBottom = sponsorTop - MainMenu.SPONSOR_PANEL_GAP;
    const loginTop = loginBottom - MainMenu.PANEL_HEIGHT;
    const panelY = loginTop + 30;
    const contentX = panelX + MainMenu.PANEL_PADDING;

    return {
      panelWidth,
      inputWidth,
      labelColumnWidth,
      rowInputWidth,
      panelX,
      sponsorTop,
      panelY,
      contentX,
    };
  }
  private setModalActive(active: boolean): void {
    if (this.usernameInput) this.usernameInput.disabled = active;
    if (this.passwordInput) this.passwordInput.disabled = active;
    if (this.startButton) this.startButton.disabled = active;
    for (const img of this.sponsorLogoEls) {
      img.style.pointerEvents = active ? "none" : "auto";
      img.style.filter = active ? "blur(4px) brightness(0.7)" : "";
    }
    this.input.enabled = !active;
  }

  constructor() {
    super({ key: "MainMenu" });
  }

  create(): void {
    const w = this.scale.width;
    const h = this.scale.height;

    
    
    
    this.input.keyboard?.resetKeys();

    if (this.textures.exists("title")) {
      this.add
        .image(w / 2, h / 2, "title")
        .setDisplaySize(w, h)
        .setDepth(DEPTH_SPLASH);
    }

    const layout = this.getPanelLayout();
    const { panelX, panelY, panelWidth, inputWidth, labelColumnWidth, rowInputWidth, sponsorTop, contentX } = layout;

    this.add
      .rectangle(
        panelX,
        panelY - 30,
        panelWidth,
        MainMenu.PANEL_HEIGHT,
        DEEP_NAVY,
        0.85,
      )
      .setStrokeStyle(2, MID_BLUE)
      .setOrigin(0, 0);

    const inputX = contentX + labelColumnWidth + MainMenu.LABEL_GAP;
    
    const labelOffsetY = 7;
    const usernameRowY = panelY - 10;
    const passwordRowY = usernameRowY + 42;

    this.loginTexts.push(
      this.add.text(contentX, usernameRowY + labelOffsetY, "Username:", {
        fontFamily: FONT_FAMILY,
        fontSize: FONT_SIZE_BODY,
        color: hex(TEXT_PRIMARY),
      }),
    );
    this.usernameInput = this.mountTextInput(
      inputX,
      usernameRowY,
      rowInputWidth,
      {
        type: "text",
        placeholder: "username",
        maxLength: 32,
        autocomplete: "username",
      },
    );

    this.loginTexts.push(
      this.add.text(contentX, passwordRowY + labelOffsetY, "Password:", {
        fontFamily: FONT_FAMILY,
        fontSize: FONT_SIZE_BODY,
        color: hex(TEXT_PRIMARY),
      }),
    );
    this.passwordInput = this.mountTextInput(
      inputX,
      passwordRowY,
      rowInputWidth,
      {
        type: "password",
        placeholder: "password",
        maxLength: 128,
        autocomplete: "current-password",
      },
    );

    this.startButton = this.mountButton(
      contentX + inputWidth,
      panelY + 78,
      "[ Log In ]",
      true,
    );

    const statusMargin = Math.min(MainMenu.PANEL_MARGIN, Math.max(16, w * 0.05));
    const statusWidth = Math.max(140, Math.min(360, w - statusMargin * 2));
    this.statusText = this.add
      .text(w - statusMargin - 14, h - 18, "Idle", {
        fontFamily: FONT_FAMILY,
        fontSize: FONT_SIZE_SMALL,
        color: hex(MainMenu.IDLE_STATUS_COLOR),
        align: "right",
        wordWrap: { width: statusWidth },
      })
      .setOrigin(1, 0.5)
      .setDepth(DEPTH_SPLASH + 2);
    this.statusDot = this.add.circle(
      w - statusMargin - 2,
      h - 18,
      4,
      MainMenu.IDLE_STATUS_COLOR,
    );
    this.statusDot.setDepth(DEPTH_SPLASH + 3);

    this.loginTexts.push(
      ...this.makePanelActionRow(contentX, panelY + 140, inputWidth, [
        {
          label: "[ Register → ]",
          onClick: () => {
            this.hideLoginForm();
            this.setModalActive(true);
            this.scene.launch("RegisterMenu");
            this.scene.pause();
          },
        },
        {
          label: "[ Source ↓ ]",
          onClick: () => window.open("/source.tar.gz", "_blank", "noopener,noreferrer"),
        },
        {
          label: "[ Leaderboard ↗ ]",
          onClick: () => window.open("/leaderboard", "_blank", "noopener,noreferrer"),
        },
      ]),
    );

    this.drawControlsPanel(h);

    this.drawSponsorsPanel(panelX, sponsorTop, panelWidth, inputWidth);

    
    
    
    
    
    const bannerWidth = Math.min(720, w - 80);
    this.clockSkewText = this.add
      .text(w / 2, 24, "", {
        fontFamily: FONT_FAMILY,
        fontSize: FONT_SIZE_BODY,
        color: hex(MainMenu.WARNING_STATUS_COLOR),
        align: "center",
        wordWrap: { width: bannerWidth },
        backgroundColor: hex(DEEP_NAVY),
        padding: { x: 16, y: 8 },
      })
      .setOrigin(0.5, 0)
      .setDepth(DEPTH_SPLASH + 1)
      .setVisible(false);
    const repositionBanner = () => {
      this.clockSkewText?.setPosition(this.scale.width / 2, 24);
      this.clockSkewText?.setWordWrapWidth(
        Math.min(720, this.scale.width - 80),
      );
    };
    this.scale.on("resize", repositionBanner);
    this.resizeHandlers.push(repositionBanner);

    const sync = getSync();
    sync.state.on("authOk", this.onAuthOk, this);
    sync.state.on("runStarted", this.onRunStarted, this);
    sync.state.on("error", this.onError, this);
    sync.state.on("serverTime", this.refreshClockSkewBanner, this);
    
    
    this.refreshClockSkewBanner();

    const kb = this.input.keyboard;
    if (kb) {
      this.readyEnterKey = kb.addKey(Phaser.Input.Keyboard.KeyCodes.ENTER, false);
      this.readyEnterKey.on("down", this.onReadyEnter, this);
    }

    this.events.on("shutdown", this.cleanup, this);
    this.events.on("resume", this.onResume, this);

    const cachedId = getCachedPlayerId();
    if (cachedId) {
      void this.resumeCachedSession(cachedId);
    } else {
      setTimeout(() => this.usernameInput?.focus(), 50);
    }
  }

  private refreshClockSkewBanner(): void {
    const t = this.clockSkewText;
    if (!t) return;
    const offset = getSync().state.serverOffsetMs;
    if (offset === undefined || Math.abs(offset) < MainMenu.CLOCK_SKEW_WARN_MS) {
      t.setVisible(false);
      return;
    }
    const seconds = (Math.abs(offset) / 1000).toFixed(1);
    const direction = offset > 0 ? "behind" : "ahead of";
    t.setText(
      `⚠ Your clock is ~${seconds}s ${direction} the server. ` +
        `Sync your system clock (NTP) — otherwise the server will refuse to start your run.`,
    );
    t.setVisible(true);
  }

  
  private drawSponsorsPanel(
    panelX: number,
    panelTop: number,
    panelWidth: number,
    inputWidth: number,
  ): void {
    this.add
      .rectangle(
        panelX,
        panelTop,
        panelWidth,
        MainMenu.SPONSOR_PANEL_HEIGHT,
        DEEP_NAVY,
        0.85,
      )
      .setStrokeStyle(2, MID_BLUE)
      .setOrigin(0, 0);

    this.add.text(
      panelX + MainMenu.PANEL_PADDING,
      panelTop + 10,
      "// sponsors",
      {
        fontFamily: FONT_FAMILY,
        fontSize: FONT_SIZE_CAPTION,
        color: hex(MID_BLUE),
      },
    );

    const count = SPONSORS.length;
    const innerWidth = inputWidth;
    const cardWidth =
      (innerWidth - MainMenu.SPONSOR_CARD_GAP * (count - 1)) / count;
    const cardsY = panelTop + 32;
    const cardsX = panelX + MainMenu.PANEL_PADDING;
    for (let i = 0; i < count; i++) {
      const cx = cardsX + i * (cardWidth + MainMenu.SPONSOR_CARD_GAP);
      this.drawSponsorCard(
        cx,
        cardsY,
        cardWidth,
        MainMenu.SPONSOR_CARD_HEIGHT,
        SPONSORS[i],
      );
    }
  }

  private drawSponsorCard(
    x: number,
    y: number,
    w: number,
    h: number,
    sponsor: SponsorSpec,
  ): void {
    
    
    
    
    const frame = this.add
      .rectangle(x, y, w, h, 0, 0)
      .setStrokeStyle(1, MID_BLUE)
      .setOrigin(0, 0);
    const glow = this.add
      .rectangle(x, y, w, h, 0, 0)
      .setStrokeStyle(2, ACCENT_PRIMARY, 0)
      .setOrigin(0, 0);
    this.sponsorHoverRects.push(frame, glow);

    let hoverTween: Phaser.Tweens.Tween | undefined;
    const setHover = (active: boolean): void => {
      if (!sponsor.url) return;
      frame.setStrokeStyle(1, active ? ACCENT_PRIMARY : MID_BLUE);
      if (hoverTween) hoverTween.stop();
      hoverTween = this.tweens.add({
        targets: glow,
        alpha: active ? 0.85 : 0,
        duration: active ? 120 : 160,
        ease: active ? "Sine.easeOut" : "Sine.easeIn",
      });
    };

    if (sponsor.url) {
      frame.setInteractive({ useHandCursor: true });
      frame.on("pointerover", () => setHover(true));
      frame.on("pointerout", () => setHover(false));
      frame.on("pointerdown", () => {
        window.open(sponsor.url, "_blank", "noopener,noreferrer");
      });
    }

    if (sponsor.imageSrc) {
      this.mountSponsorImage(x, y, w, h, sponsor, setHover);
    } else {
      this.add
        .text(x + w / 2, y + h / 2, sponsor.placeholder, {
          fontFamily: FONT_FAMILY,
          fontSize: "24px",
          color: hex(TEXT_PRIMARY),
        })
        .setOrigin(0.5);
    }
  }

  
  private mountSponsorImage(
    sceneX: number,
    sceneY: number,
    sceneW: number,
    sceneH: number,
    sponsor: SponsorSpec,
    onHoverChange?: (active: boolean) => void,
  ): void {
    const canvas = this.game.canvas;
    const parent = canvas.parentElement ?? document.body;
    const img = document.createElement("img");
    img.src = sponsor.imageSrc!;
    img.alt = sponsor.label;
    img.draggable = false;
    Object.assign(img.style, {
      position: "absolute",
      zIndex: "19",
      objectFit: "contain",
      padding: "4px",
      boxSizing: "border-box",
      cursor: sponsor.url ? "pointer" : "default",
      userSelect: "none",
      pointerEvents: "auto",
      transition: sponsor.url ? "transform 140ms ease, filter 140ms ease" : "none",
    } as Partial<CSSStyleDeclaration>);

    if (!parent.style.position) parent.style.position = "relative";
    parent.appendChild(img);
    this.sponsorLogoEls.push(img);

    if (sponsor.url) {
      img.addEventListener("click", () => {
        window.open(sponsor.url, "_blank", "noopener,noreferrer");
      });
      img.addEventListener("mouseenter", () => {
        onHoverChange?.(true);
        img.style.transform = "translateY(-1px) scale(1.03)";
        img.style.filter = "brightness(1.08)";
      });
      img.addEventListener("mouseleave", () => {
        onHoverChange?.(false);
        img.style.transform = "";
        img.style.filter = "";
      });
    }

    const place = () => {
      const rect = canvas.getBoundingClientRect();
      const parentRect = parent.getBoundingClientRect();
      const scaleX = rect.width / this.scale.width;
      img.style.left = `${rect.left - parentRect.left + sceneX * scaleX}px`;
      img.style.top = `${rect.top - parentRect.top + sceneY * scaleX}px`;
      img.style.width = `${sceneW * scaleX}px`;
      img.style.height = `${sceneH * scaleX}px`;
    };
    place();
    window.addEventListener("resize", place);
    this.scale.on("resize", place);
    this.resizeHandlers.push(place);
  }

  private async connectForAuth(): Promise<boolean> {
    const sync = getSync();
    if (sync.isConnected()) return true;

    this.setStatus("Connecting", MainMenu.WARNING_STATUS_COLOR);
    try {
      await sync.connect(WS_URL);
      return true;
    } catch (err) {
      console.error("[MainMenu] connect failed", err);
      this.setStatus("Connection failed. Refresh to retry.", MainMenu.ERROR_STATUS_COLOR);
      return false;
    }
  }

  private async resumeCachedSession(playerId: string): Promise<void> {
    this.hideLoginForm();
    this.setStatus("Resuming", MainMenu.WARNING_STATUS_COLOR);
    this.submitting = true;

    if (!(await this.connectForAuth())) {
      this.submitting = false;
      this.showLoginForm();
      return;
    }

    getSync().sendAuth(playerId);
  }

  private hideLoginForm(): void {
    if (this.usernameInput) this.usernameInput.style.display = "none";
    if (this.passwordInput) this.passwordInput.style.display = "none";
    if (this.startButton) this.startButton.style.display = "none";
    for (const text of this.loginTexts) text.setVisible(false);
    
    
    if (
      document.activeElement === this.usernameInput ||
      document.activeElement === this.passwordInput ||
      document.activeElement === this.startButton
    ) {
      (document.activeElement as HTMLElement).blur();
    }
  }

  private showLoginForm(): void {
    if (this.usernameInput) this.usernameInput.style.display = "";
    if (this.passwordInput) this.passwordInput.style.display = "";
    if (this.startButton) this.startButton.style.display = "";
    for (const text of this.loginTexts) text.setVisible(true);
    this.clearReadyView();
    this.readyActive = false;
    this.setStatus("Idle", MainMenu.IDLE_STATUS_COLOR);
  }

  private showReadyView(displayName: string): void {
    this.hideLoginForm();
    this.clearReadyView();
    this.readyActive = true;

    const { panelY, contentX, inputWidth } = this.getPanelLayout();
    const buttonY = panelY + 43;
    const footerY = panelY + 140;

    const cat = this.add.text(contentX, panelY - 8, "Cat", {
      fontFamily: FONT_FAMILY,
      fontSize: FONT_SIZE_BODY,
      color: hex(TEXT_PRIMARY),
    });
    const name = this.add.text(contentX + 42, panelY - 10, displayName, {
      fontFamily: FONT_FAMILY,
      fontSize: FONT_SIZE_BODY,
      color: hex(ACCENT_PRIMARY),
    });
    const comma = this.add.text(name.x + name.displayWidth, panelY - 8, ",", {
      fontFamily: FONT_FAMILY,
      fontSize: FONT_SIZE_BODY,
      color: hex(TEXT_PRIMARY),
    });
    const prompt = this.add.text(
      comma.x + comma.displayWidth + 8,
      panelY - 8,
      "proceed.",
      {
        fontFamily: FONT_FAMILY,
        fontSize: FONT_SIZE_BODY,
        color: hex(TEXT_PRIMARY),
      },
    );
    const startWidth = Math.floor(inputWidth * 0.46) + 10;
    const startX = contentX + (inputWidth - startWidth) / 2;
    const start = this.makeReadyPrimaryButton(startX, buttonY, startWidth, 46, "START", () =>
      this.startAuthenticatedRun(),
    );
    const hint = this.add
      .text(contentX + inputWidth / 2, buttonY + 62, "Press [ Enter ] or click Start to begin.", {
        fontFamily: FONT_FAMILY,
        fontSize: FONT_SIZE_SMALL,
        color: hex(TEXT_MUTED),
        wordWrap: { width: inputWidth },
      })
      .setOrigin(0.5, 0);
    const actions = this.makePanelActionRow(contentX, footerY, inputWidth, [
      { label: "[ ← Log Out ]", onClick: () => this.logoutReadySession() },
      {
        label: "[ Source ↓ ]",
        onClick: () => window.open("/source.tar.gz", "_blank", "noopener,noreferrer"),
      },
      {
        label: "[ Leaderboard ↗ ]",
        onClick: () => window.open("/leaderboard", "_blank", "noopener,noreferrer"),
      },
    ]);

    this.readyTexts.push(
      cat,
      name,
      comma,
      prompt,
      hint,
      ...start,
      ...actions,
    );
    this.setStatus("Authenticated", MainMenu.SUCCESS_STATUS_COLOR);
  }

  private setStatus(message: string, color: number): void {
    const visible = message.length > 0;
    this.statusDot?.setVisible(visible);
    this.statusText?.setVisible(visible);
    if (!visible) return;
    const displayColor = color;
    this.statusDot?.setFillStyle(displayColor);
    this.statusText?.setText(message);
    this.statusText?.setColor(hex(displayColor));
  }

  private clearReadyView(): void {
    for (const obj of this.readyTexts) obj.destroy();
    this.readyTexts = [];
  }

  private makeReadyPrimaryButton(
    x: number,
    y: number,
    width: number,
    height: number,
    label: string,
    onClick: () => void,
  ): Phaser.GameObjects.GameObject[] {
    const bg = this.add
      .rectangle(x, y, width, height, ACCENT_PRIMARY, 0)
      .setOrigin(0, 0)
      .setStrokeStyle(2, TEXT_PRIMARY)
      .setInteractive({ useHandCursor: true });
    const text = this.add
      .text(x + width / 2, y + height / 2, label, {
        fontFamily: FONT_FAMILY,
        fontSize: "20px",
        color: hex(ACCENT_PRIMARY),
      })
      .setOrigin(0.5)
      .setInteractive({ useHandCursor: true });
    text.setLetterSpacing(4);

    const setHover = (active: boolean): void => {
      bg.setFillStyle(ACCENT_PRIMARY, active ? 1 : 0);
      bg.setStrokeStyle(2, TEXT_PRIMARY);
      text.setColor(active ? hex(DEEP_NAVY) : hex(ACCENT_PRIMARY));
    };

    bg.on("pointerover", () => setHover(true));
    bg.on("pointerout", () => setHover(false));
    text.on("pointerover", () => setHover(true));
    text.on("pointerout", () => setHover(false));
    bg.on("pointerdown", onClick);
    text.on("pointerdown", onClick);

    return [bg, text];
  }

  private makePanelActionRow(
    x: number,
    y: number,
    width: number,
    actions: ReadonlyArray<{ label: string; onClick: () => void }>,
  ): Phaser.GameObjects.Text[] {
    const columns = [width / 6, width / 2 - 5, (width * 5) / 6];
    return actions.map((action, i) =>
      this.makeReadyAction(x + columns[i], y, action.label, action.onClick, "center"),
    );
  }

  private makeReadyAction(
    x: number,
    y: number,
    label: string,
    onClick: () => void,
    align: "left" | "center" | "right" = "left",
  ): Phaser.GameObjects.Text {
    const originX = align === "right" ? 1 : align === "center" ? 0.5 : 0;
    const text = this.add
      .text(x, y, label, {
        fontFamily: FONT_FAMILY,
        fontSize: FONT_SIZE_SMALL,
        color: hex(TEXT_PRIMARY),
      })
      .setOrigin(originX, 0)
      .setInteractive({ useHandCursor: true });
    text.on("pointerover", () => text.setColor(hex(ACCENT_PRIMARY)));
    text.on("pointerout", () => text.setColor(hex(TEXT_PRIMARY)));
    text.on("pointerdown", onClick);
    return text;
  }

  private onReadyEnter(): void {
    if (!this.readyActive || this.submitting) return;
    const active = document.activeElement;
    if (active === this.usernameInput || active === this.passwordInput) return;
    this.startAuthenticatedRun();
  }

  private startAuthenticatedRun(): void {
    if (this.submitting) return;
    this.submitting = true;
    this.readyActive = false;
    this.clearReadyView();
    this.setStatus("Starting", MainMenu.WARNING_STATUS_COLOR);
    getSync().sendStartRun();
  }

  private logoutReadySession(): void {
    clearCachedPlayerId();
    resetSync();
    this.scene.restart();
  }

  private drawControlsPanel(sceneHeight: number): void {
    const panelX = MainMenu.PANEL_MARGIN;
    const panelHeight = 196;
    const panelTop = sceneHeight - panelHeight - MainMenu.PANEL_MARGIN;
    const panelWidth = 248;
    const paddingX = 16;
    const actionX = panelX + paddingX;
    const keyX = panelX + panelWidth - paddingX;
    const rowY = panelTop + 38;

    this.add
      .rectangle(panelX, panelTop, panelWidth, panelHeight, DEEP_NAVY, 0.68)
      .setStrokeStyle(2, MID_BLUE)
      .setOrigin(0, 0);

    this.controlsTexts.push(
      this.add.text(actionX, panelTop + 10, "// controls", {
        fontFamily: FONT_FAMILY,
        fontSize: FONT_SIZE_CAPTION,
        color: hex(MID_BLUE),
      }),
      this.add
        .text(actionX, rowY, "Action", {
          fontFamily: FONT_FAMILY,
          fontSize: FONT_SIZE_CAPTION,
          color: hex(TEXT_MUTED),
        })
        .setAlpha(0.9),
      this.add
        .text(keyX, rowY, "Key", {
          fontFamily: FONT_FAMILY,
          fontSize: FONT_SIZE_CAPTION,
          color: hex(TEXT_MUTED),
        })
        .setOrigin(1, 0)
        .setAlpha(0.9),
    );

    for (let i = 0; i < CONTROL_BINDINGS.length; i++) {
      const [action, key] = CONTROL_BINDINGS[i];
      const y = rowY + 22 + i * 19;
      this.controlsTexts.push(
        this.add.text(actionX, y, action, {
          fontFamily: FONT_FAMILY,
          fontSize: FONT_SIZE_CAPTION,
          color: hex(TEXT_PRIMARY),
        }),
        this.add
          .text(keyX, y, key, {
            fontFamily: FONT_FAMILY,
            fontSize: FONT_SIZE_CAPTION,
            color: hex(TEXT_PRIMARY),
          })
          .setOrigin(1, 0),
      );
    }
  }

  private onResume(): void {
    this.setModalActive(false);
    this.showLoginForm();
    this.input.keyboard?.resetKeys();
    setTimeout(() => this.usernameInput?.focus(), 50);
  }

  
  private mountTextInput(
    sceneX: number,
    sceneY: number,
    widthPx: number,
    opts: {
      type: "text" | "password";
      placeholder: string;
      maxLength: number;
      autocomplete: AutoFill;
    },
  ): HTMLInputElement {
    const canvas = this.game.canvas;
    const parent = canvas.parentElement ?? document.body;
    const input = document.createElement("input");
    input.type = opts.type;
    input.maxLength = opts.maxLength;
    input.placeholder = opts.placeholder;
    input.autocomplete = opts.autocomplete;
    input.spellcheck = false;
    Object.assign(input.style, {
      position: "absolute",
      zIndex: "20",
      fontFamily: "monospace",
      fontSize: "18px",
      padding: "6px 10px",
      border: `1px solid ${hex(MID_BLUE)}`,
      background: hex(DEEP_NAVY),
      color: hex(TEXT_PRIMARY),
      width: `${widthPx}px`,
      outline: "none",
      boxSizing: "border-box",
    } as Partial<CSSStyleDeclaration>);

    input.addEventListener("focus", () => {
      input.style.borderColor = hex(ACCENT_PRIMARY);
    });
    input.addEventListener("blur", () => {
      input.style.borderColor = hex(MID_BLUE);
    });

    if (!parent.style.position) parent.style.position = "relative";
    parent.appendChild(input);

    const place = () => {
      const rect = canvas.getBoundingClientRect();
      const parentRect = parent.getBoundingClientRect();
      const scaleX = rect.width / this.scale.width;
      const leftInCanvas = sceneX * scaleX;
      const topInCanvas = sceneY * scaleX;
      input.style.left = `${rect.left - parentRect.left + leftInCanvas}px`;
      input.style.top = `${rect.top - parentRect.top + topInCanvas}px`;
      const visualWidth = widthPx * scaleX;
      input.style.width = `${visualWidth}px`;
    };
    place();
    window.addEventListener("resize", place);
    this.scale.on("resize", place);
    this.resizeHandlers.push(place);

    input.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") this.onStart();
    });

    return input;
  }

  
  private mountButton(
    sceneX: number,
    sceneY: number,
    label: string,
    rightAligned = false,
  ): HTMLButtonElement {
    const canvas = this.game.canvas;
    const parent = canvas.parentElement ?? document.body;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = label;
    Object.assign(btn.style, {
      position: "absolute",
      zIndex: "20",
      fontFamily: "monospace",
      fontSize: "16px",
      padding: "0",
      border: "none",
      background: "transparent",
      color: hex(ACCENT_PRIMARY),
      cursor: "pointer",
      outline: "none",
      whiteSpace: "nowrap",
    } as Partial<CSSStyleDeclaration>);

    const setHover = (on: boolean) => {
      btn.style.color = on ? BUTTON_HOVER_COLOR : hex(ACCENT_PRIMARY);
    };
    btn.addEventListener("focus", () => setHover(true));
    btn.addEventListener("blur", () => setHover(false));
    btn.addEventListener("mouseenter", () => setHover(true));
    btn.addEventListener("mouseleave", () => {
      
      
      if (document.activeElement !== btn) setHover(false);
    });
    btn.addEventListener("click", () => this.onStart());

    if (!parent.style.position) parent.style.position = "relative";
    parent.appendChild(btn);

    const place = () => {
      const rect = canvas.getBoundingClientRect();
      const parentRect = parent.getBoundingClientRect();
      const scaleX = rect.width / this.scale.width;
      btn.style.left = `${rect.left - parentRect.left + sceneX * scaleX}px`;
      btn.style.top = `${rect.top - parentRect.top + sceneY * scaleX}px`;
      btn.style.fontSize = `${16 * scaleX}px`;
      btn.style.transform = rightAligned ? "translateX(-100%)" : "";
    };
    place();
    window.addEventListener("resize", place);
    this.scale.on("resize", place);
    this.resizeHandlers.push(place);

    return btn;
  }

  private async onStart(): Promise<void> {
    if (this.submitting) return;
    const username = this.usernameInput?.value.trim() ?? "";
    const password = this.passwordInput?.value ?? "";
    if (!username || !password) {
      this.setStatus("Missing username or password", MainMenu.ERROR_STATUS_COLOR);
      return;
    }

    this.submitting = true;
    this.setStatus("Logging in", MainMenu.WARNING_STATUS_COLOR);

    try {
      const res = await fetch("/api/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      
      
      
      
      const dateHeader = res.headers.get("Date");
      if (dateHeader) {
        const serverNow = Date.parse(dateHeader);
        if (!Number.isNaN(serverNow)) {
          getSync().state.setServerTime(serverNow);
          this.refreshClockSkewBanner();
        }
      }
      if (!res.ok) {
        const body = (await res.json().catch(() => ({}))) as {
          error?: string;
        };
        this.setStatus(body.error ?? `Login failed (HTTP ${res.status})`, MainMenu.ERROR_STATUS_COLOR);
        this.submitting = false;
        return;
      }
      const body = (await res.json()) as {
        player_id: string;
        display_name: string;
      };

      
      
      
      
      
      
      try {
        await this.waitForQueueAdmission(body.player_id, password);
      } catch (err) {
        console.error("[MainMenu] queue: failed", err);
        this.setStatus(err instanceof Error ? err.message : "Queue error", MainMenu.ERROR_STATUS_COLOR);
        this.submitting = false;
        return;
      }

      if (!(await this.connectForAuth())) {
        this.submitting = false;
        return;
      }

      this.setStatus("Authenticating", MainMenu.WARNING_STATUS_COLOR);
      
      
      
      
      setCachedPlayerId(body.player_id);
      getSync().sendAuth(body.player_id);
    } catch (err) {
      console.error("[MainMenu] login failed", err);
      this.setStatus("Network error. Try again", MainMenu.ERROR_STATUS_COLOR);
      this.submitting = false;
    }
  }

  
  private async waitForQueueAdmission(
    playerId: string,
    password: string,
  ): Promise<boolean> {
    if (!getConfig().queue_enabled) return true;

    let res: Response;
    try {
      res = await fetch("/api/queue/join", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ player_id: playerId, password }),
      });
    } catch {
      throw new Error("Network error contacting queue.");
    }
    if (res.status === 503) {
      
      return false;
    }
    if (res.status === 409) {
      
      
    } else if (!res.ok) {
      
      
      
      const text = (await res.text().catch(() => "")).trim();
      throw new Error(text || `Queue join failed (HTTP ${res.status}).`);
    } else {
      const body = (await res.json()) as {
        position: number;
        est_wait_ms: number;
        admitted: boolean;
      };
      if (body.admitted) return true;
      this.renderQueueStatus(body.position, body.est_wait_ms);
    }

    
    
    
    const pollMs = 2000;
    while (true) {
      await new Promise((r) => setTimeout(r, pollMs));
      let statusRes: Response;
      try {
        statusRes = await fetch(
          "/api/queue/status/" + encodeURIComponent(playerId),
        );
      } catch {
        
        
        continue;
      }
      if (statusRes.status === 404) {
        
        
        throw new Error("Queue slot expired. Log in again.");
      }
      if (!statusRes.ok) {
        
        
        
        
        if (statusRes.status === 503) return false;
        continue;
      }
      const status = (await statusRes.json()) as {
        position: number;
        est_wait_ms: number;
        admitted: boolean;
      };
      if (status.admitted) return true;
      this.renderQueueStatus(status.position, status.est_wait_ms);
    }
  }

  private renderQueueStatus(position: number, estWaitMs: number): void {
    
    
    
    const minutes = Math.max(0, Math.ceil(estWaitMs / 60_000));
    const wait = minutes <= 1 ? "<1 min" : `~${minutes} min`;
    
    
    
    
    
    const message =
      position > 0
        ? `In queue: ${this.formatOrdinal(position)} in line · ${wait} wait`
        : `Queue status: Checking admission… · ${wait} wait`;
    this.setStatus(message, MainMenu.WARNING_STATUS_COLOR);
  }

  
  private formatOrdinal(n: number): string {
    const mod100 = n % 100;
    if (mod100 >= 11 && mod100 <= 13) return `${n}th`;
    switch (n % 10) {
      case 1:
        return `${n}st`;
      case 2:
        return `${n}nd`;
      case 3:
        return `${n}rd`;
      default:
        return `${n}th`;
    }
  }

  private onAuthOk(_displayName: string): void {
    this.submitting = false;
    this.showReadyView(_displayName);
  }

  private onRunStarted(): void {
    this.scene.start("Game");
    this.scene.launch("GameHUD");
  }

  private onError(err: { code: string; message: string }): void {
    
    
    
    if (err.code !== "disconnected") {
      clearCachedPlayerId();
      this.showLoginForm();
    }
    this.readyActive = false;
    this.clearReadyView();
    this.setStatus(`Error: ${err.message}`, MainMenu.ERROR_STATUS_COLOR);
    this.submitting = false;
  }

  private cleanup(): void {
    const sync = getSync();
    sync.state.off("authOk", this.onAuthOk, this);
    sync.state.off("runStarted", this.onRunStarted, this);
    sync.state.off("error", this.onError, this);
    this.events.off("resume", this.onResume, this);
    this.readyEnterKey?.off("down", this.onReadyEnter, this);
    this.readyEnterKey = undefined;
    sync.state.off("serverTime", this.refreshClockSkewBanner, this);
    for (const fn of this.resizeHandlers) {
      window.removeEventListener("resize", fn);
      this.scale.off("resize", fn);
    }
    this.resizeHandlers = [];

    this.usernameInput?.remove();
    this.usernameInput = undefined;
    this.passwordInput?.remove();
    this.passwordInput = undefined;
    this.startButton?.remove();
    this.startButton = undefined;
    this.statusDot?.destroy();
    this.statusDot = undefined;
    this.statusText?.destroy();
    this.statusText = undefined;

    for (const el of this.sponsorLogoEls) el.remove();
    this.sponsorLogoEls = [];

    for (const text of this.controlsTexts) text.destroy();
    this.controlsTexts = [];

    this.clearReadyView();
    this.loginTexts = [];

    for (const rect of this.sponsorHoverRects) rect.destroy();
    this.sponsorHoverRects = [];

    
    
    
    
    this.submitting = false;
    this.readyActive = false;
  }
}

export default MainMenu;
