export function collectPythonMessages(apiRoot?: string): Set<string>;
export function collectTypeScriptMessages(): Set<string>;
export function sortedCatalog(messages: Set<string>): Record<string, string>;
