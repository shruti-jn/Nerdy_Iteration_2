import "@testing-library/jest-dom";

// jsdom does not implement scrollIntoView
window.HTMLElement.prototype.scrollIntoView = function () {};

// jsdom may not provide a fully functional localStorage in all environments.
// Provide a simple mock that satisfies getItem/setItem/removeItem.
if (typeof globalThis.localStorage === "undefined" || !globalThis.localStorage?.getItem) {
  const store: Record<string, string> = {};
  Object.defineProperty(globalThis, "localStorage", {
    value: {
      getItem: (key: string) => store[key] ?? null,
      setItem: (key: string, value: string) => { store[key] = String(value); },
      removeItem: (key: string) => { delete store[key]; },
      clear: () => { for (const k of Object.keys(store)) delete store[k]; },
      get length() { return Object.keys(store).length; },
      key: (index: number) => Object.keys(store)[index] ?? null,
    },
    writable: true,
  });
}
