/// <reference types="vite/client" />

declare module "d3-force-3d" {
  export function forceCollide<NodeDatum = unknown>(
    radius?: number | ((node: NodeDatum) => number)
  ): {
    radius: (radius: number | ((node: NodeDatum) => number)) => unknown;
    strength: (strength: number) => unknown;
    iterations: (n: number) => unknown;
  };
}

interface ImportMetaEnv {
  readonly VITE_API_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
