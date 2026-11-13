const statusElement = document.querySelector<HTMLParagraphElement>("#status");

type Health = {
  status: string;
  service: string;
  version: string;
};

async function checkApi(): Promise<void> {
  if (!statusElement) {
    return;
  }
  try {
    const response = await fetch("/healthz");
    if (!response.ok) {
      throw new Error(`health check returned ${response.status}`);
    }
    const health = (await response.json()) as Health;
    statusElement.textContent = `API ${health.status} (${health.service} ${health.version})`;
    statusElement.dataset.state = "ok";
  } catch (error) {
    const detail = error instanceof Error ? error.message : "unknown error";
    statusElement.textContent = `API unavailable: ${detail}`;
    statusElement.dataset.state = "error";
  }
}

void checkApi();
