/** Runtime configuration, fetched from `/config.json` rather than baked
 * into the build -- the same static bundle must work against whichever
 * OIDC provider a deployment points it at (ADR-013, "no provider-specific
 * code"). `apps/console/Dockerfile`'s image generates this file from
 * environment variables at container start; local `vite dev` expects a
 * `public/config.json` (see `public/config.json.example`). */
export type OidcConfig = {
  issuer: string;
  clientId: string;
  redirectUri: string;
  scope: string;
};

export type ConsoleConfig = {
  oidc: OidcConfig;
};

let cached: ConsoleConfig | null = null;
let configUrl = "/config.json";

/** Test-only override, mirroring `api.ts`'s `setApiBase`. */
export function setConfigUrl(url: string): void {
  configUrl = url;
  cached = null;
}

export async function loadConfig(): Promise<ConsoleConfig> {
  if (cached) {
    return cached;
  }
  const response = await fetch(configUrl);
  if (!response.ok) {
    throw new Error(
      `could not load console configuration from ${configUrl} (${response.status}) -- ` +
        "see apps/console/public/config.json.example",
    );
  }
  const config = (await response.json()) as ConsoleConfig;
  if (!config.oidc?.issuer || !config.oidc?.clientId || !config.oidc?.redirectUri) {
    throw new Error("console configuration is missing required oidc settings");
  }
  cached = config;
  return config;
}

/** Test-only: inject configuration directly instead of mocking fetch. */
export function setConfigForTests(config: ConsoleConfig): void {
  cached = config;
}
