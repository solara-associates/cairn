export type Route = { name: string; render: (container: HTMLElement) => void | Promise<void> };

export class Router {
  private readonly routes = new Map<string, Route>();

  constructor(
    private readonly container: HTMLElement,
    private readonly defaultRoute: string,
  ) {}

  register(route: Route): void {
    this.routes.set(route.name, route);
  }

  /** Navigates without touching ``location.hash`` -- used by tests and by
   * a screen moving the journey forward programmatically, so a step
   * transition doesn't depend on the browser's hashchange event firing. */
  async go(name: string): Promise<void> {
    const route = this.routes.get(name) ?? this.routes.get(this.defaultRoute);
    if (!route) {
      throw new Error(`no route registered: ${name}`);
    }
    this.container.innerHTML = "";
    await route.render(this.container);
  }

  start(): void {
    const fromHash = () => this.go(window.location.hash.replace(/^#/, "") || this.defaultRoute);
    window.addEventListener("hashchange", fromHash);
    void fromHash();
  }
}
