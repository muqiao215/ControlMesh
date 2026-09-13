import { object, requireThat } from "./value";

/** Explicit trusted host configuration; never inherit the controller's environment. */
export function hostJobEnvironment(value?: unknown): Readonly<Record<string, string>> {
  requireThat(value === undefined || (object(value) && Object.keys(value).length <= 128
    && Object.entries(value).every(([key, entry]) => /^[A-Za-z_][A-Za-z0-9_]*$/.test(key)
      && typeof entry === "string" && !entry.includes("\0") && Buffer.byteLength(entry) <= 32768)), "invalid_host_environment");
  const env = { PATH: "/usr/bin:/bin", LANG: "C.UTF-8", ...(value as Record<string, string> | undefined) };
  requireThat(Buffer.byteLength(JSON.stringify(env)) <= 131072, "host_environment_too_large");
  return Object.freeze(env);
}
