import { GameState } from "./GameState";
import type { S2CEnvelope } from "../../net/packet";


export class SpectatorSync {
  state = new GameState();
  private ws?: WebSocket;
  private connected = false;

  connect(url: string): Promise<void> {
    return new Promise<void>((resolve, reject) => {
      let settled = false;
      let ws: WebSocket;
      try {
        ws = new WebSocket(url);
      } catch (err) {
        reject(err);
        return;
      }
      this.ws = ws;

      ws.onopen = () => {
        this.connected = true;
        if (!settled) {
          settled = true;
          resolve();
        }
      };

      ws.onerror = (ev) => {
        if (!settled) {
          settled = true;
          reject(ev);
        }
      };

      ws.onmessage = (ev: MessageEvent) => {
        this.onMessage(typeof ev.data === "string" ? ev.data : String(ev.data));
      };

      ws.onclose = () => {
        this.connected = false;
        
        
        
        this.state.emit("disconnect");
      };
    });
  }

  close(): void {
    if (this.ws) {
      try {
        this.ws.close();
      } catch {
        
      }
    }
    this.ws = undefined;
    this.connected = false;
  }

  isConnected(): boolean {
    return this.connected && this.ws?.readyState === WebSocket.OPEN;
  }

  private onMessage(raw: string): void {
    let env: S2CEnvelope;
    try {
      env = JSON.parse(raw) as S2CEnvelope;
    } catch {
      return;
    }
    this.state.apply(env);
  }
}
