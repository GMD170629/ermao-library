import { AbortSignalCancellationToken } from '../../server-connection/public';
import type {
  AppFlowCancellationFactory,
  AppFlowCancellationSource,
} from '../application/ports';

class AbortAppFlowCancellationSource implements AppFlowCancellationSource {
  private readonly controller = new AbortController();
  readonly token = new AbortSignalCancellationToken(this.controller.signal);

  cancel(): void {
    this.controller.abort();
  }
}

export class AbortAppFlowCancellationFactory
  implements AppFlowCancellationFactory
{
  create(): AppFlowCancellationSource {
    return new AbortAppFlowCancellationSource();
  }
}
