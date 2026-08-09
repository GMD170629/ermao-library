import { AbortSignalCancellationToken } from '../../server-connection/public';
import type {
  LibraryCancellationFactory,
  LibraryCancellationSource,
} from '../application/ports';

class AbortLibraryCancellationSource implements LibraryCancellationSource {
  private readonly controller = new AbortController();
  readonly token = new AbortSignalCancellationToken(this.controller.signal);

  cancel(): void {
    this.controller.abort();
  }
}

export class AbortLibraryCancellationFactory
  implements LibraryCancellationFactory
{
  create(): LibraryCancellationSource {
    return new AbortLibraryCancellationSource();
  }
}
