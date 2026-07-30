export interface Clock {
  nowMs(): number;
}

export interface IdGenerator {
  nextId(): string;
}

export class SystemClock implements Clock {
  nowMs(): number {
    return Date.now();
  }
}
