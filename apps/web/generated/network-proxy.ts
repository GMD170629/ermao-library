/* eslint-disable */
// AUTO-GENERATED from the network-proxy FastAPI OpenAPI contract.
// Run pnpm --filter @shuku/web generate:network-proxy-api; do not edit by hand.

export type ConnectionView = {
  protocol: "http" | "socks5";
  host: string;
  port: number;
  username: string;
  passwordConfigured: boolean;
};

export type NetworkProxyView = {
  connection: ConnectionView | null;
  presets: Array<"updates" | "github" | "bangumi">;
  domains: Array<string>;
  presetDomains: {
    [key: string]: Array<string> | null | undefined;
  };
};

export type ProxyProbe = {
  host: string;
  rules: Array<string>;
  result: "connected" | "timeout" | "authentication" | "failed";
  status?: number | null;
};

export type StoredConnection = {
  protocol: "http" | "socks5";
  host: string;
  port: number;
  username?: string;
  password?: string | null;
};

export type StoredProxy = {
  connection?: StoredConnection | null;
  presets?: Array<"updates" | "github" | "bangumi">;
  domains?: Array<string>;
};
