export type AudioPlayOutcome =
  | { type: 'playing' }
  | { type: 'superseded' }
  | { type: 'failed'; reason: unknown };

/** A later play, pause, source switch or disposal owns the transport outcome. */
export class AudioPlayAttempt {
  private generation = 0;

  cancel(): void {
    this.generation += 1;
  }

  async run(start: () => Promise<void>): Promise<AudioPlayOutcome> {
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
}
