export type AudioPlayOutcome =
  | { type: 'playing' }
  | { type: 'superseded' }
  | { type: 'failed'; reason: unknown };

/** A later play, pause, source switch or disposal owns the transport outcome. */
export class AudioPlaybackAttempt {
  private generation = 0;
  private pendingClose: object | null = null;

  cancelPendingClose(): void {
    this.pendingClose = null;
  }

  cancel(): void {
    this.generation += 1;
    this.cancelPendingClose();
  }

  async run(start: () => Promise<void>): Promise<AudioPlayOutcome> {
    this.cancelPendingClose();
    const generation = ++this.generation;
    try {
      await start();
      return { type: generation === this.generation ? 'playing' : 'superseded' };
    } catch (reason) {
      return generation === this.generation
        ? { type: 'failed', reason }
        : { type: 'superseded' };
    }
  }

  async close(saveLocally: () => Promise<boolean>, reset: () => void): Promise<void> {
    const intent = {};
    this.pendingClose = intent;
    try {
      const saved = await saveLocally();
      if (this.pendingClose === intent && saved) reset();
    } finally {
      if (this.pendingClose === intent) this.pendingClose = null;
    }
  }
}
