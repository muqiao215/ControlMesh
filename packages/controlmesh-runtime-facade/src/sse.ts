export interface StreamSseOptions {
  token?: string;
  fetch?: typeof fetch;
}

export async function* streamSse<T>(
  url: string,
  options: StreamSseOptions = {},
): AsyncIterable<T> {
  const fetchImpl = options.fetch ?? fetch;
  const headers = new Headers({ Accept: "text/event-stream" });
  if (options.token) {
    headers.set("Authorization", `Bearer ${options.token}`);
  }

  const response = await fetchImpl(url, { headers });
  if (!response.ok || response.body === null) {
    throw new Error(`SSE request failed with status ${response.status}`);
  }

  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) {
      break;
    }
    buffer += value;
    let splitAt = buffer.indexOf("\n\n");
    while (splitAt !== -1) {
      const frame = buffer.slice(0, splitAt);
      buffer = buffer.slice(splitAt + 2);
      const data = frame
        .split("\n")
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).trimStart())
        .join("\n");
      if (data) {
        yield JSON.parse(data) as T;
      }
      splitAt = buffer.indexOf("\n\n");
    }
  }
}
