export interface QqBotConfig {
  onebotWsUrl: string;
  onebotToken: string;
  controlmeshWsUrl: string;
  controlmeshToken: string;
  controlmeshTransport: string;
  allowFrom: "*" | Set<string>;
  hookHost: string;
  hookPort: number;
  hookToken: string;
  targetsPath: string;
  outboundTempDir: string;
}

function requireEnv(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) {
    throw new Error(`Missing required environment variable: ${name}`);
  }
  return value;
}

function parseAllowFrom(raw: string | undefined): "*" | Set<string> {
  const value = raw?.trim() ?? "*";
  if (!value || value === "*") {
    return "*";
  }
  return new Set(
    value
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean),
  );
}

export function loadConfig(): QqBotConfig {
  return {
    onebotWsUrl: process.env.CONTROLMESH_QQBOT_ONEBOT_WS_URL?.trim() || "ws://127.0.0.1:3001",
    onebotToken: process.env.CONTROLMESH_QQBOT_ONEBOT_TOKEN?.trim() || "",
    controlmeshWsUrl: requireEnv("CONTROLMESH_QQBOT_CONTROLMESH_WS_URL"),
    controlmeshToken: requireEnv("CONTROLMESH_QQBOT_CONTROLMESH_TOKEN"),
    controlmeshTransport: process.env.CONTROLMESH_QQBOT_CONTROLMESH_TRANSPORT?.trim() || "qq",
    allowFrom: parseAllowFrom(process.env.CONTROLMESH_QQBOT_ALLOW_FROM),
    hookHost: process.env.CONTROLMESH_QQBOT_HOOK_HOST?.trim() || "127.0.0.1",
    hookPort: Number(process.env.CONTROLMESH_QQBOT_HOOK_PORT || "3187"),
    hookToken: requireEnv("CONTROLMESH_QQBOT_HOOK_TOKEN"),
    targetsPath:
      process.env.CONTROLMESH_QQBOT_TARGETS_PATH?.trim() || ".controlmesh-qqbot-targets.json",
    outboundTempDir:
      process.env.CONTROLMESH_QQBOT_OUTBOUND_TEMP_DIR?.trim() ||
      ".controlmesh-qqbot-outbound",
  };
}

export function isAllowedUser(config: QqBotConfig, userId: string): boolean {
  if (config.allowFrom === "*") {
    return true;
  }
  return config.allowFrom.has(userId);
}
