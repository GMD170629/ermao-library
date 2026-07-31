export interface SnapshotOperationCoordinator {
  run<Result>(
    directory: string,
    operation: () => Promise<Result>,
  ): Promise<Result>;
}

export class InProcessSnapshotOperationCoordinator
  implements SnapshotOperationCoordinator
{
  private readonly operationTails = new Map<string, Promise<void>>();

  run<Result>(
    directory: string,
    operation: () => Promise<Result>,
  ): Promise<Result> {
    const previous =
      this.operationTails.get(directory) ?? Promise.resolve();
    const result = previous.then(operation, operation);
    const tail = result.then(
      () => undefined,
      () => undefined,
    );
    this.operationTails.set(directory, tail);

    return result.finally(() => {
      if (this.operationTails.get(directory) === tail) {
        this.operationTails.delete(directory);
      }
    });
  }
}
