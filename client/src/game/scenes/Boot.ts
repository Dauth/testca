import Phaser from "phaser";


export class Boot extends Phaser.Scene {
  constructor() {
    super({ key: "Boot" });
  }

  preload(): void {
    
    
    const PX =
      "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=";
    this.load.image("__fallback_pixel", PX);
  }

  create(): void {
    this.scene.start("Preloader");
  }
}

export default Boot;
