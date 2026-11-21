import { createContext, useContext } from "react";
import type { Edition } from "./types";

export interface EditionState {
  edition: Edition;
  setEdition: (edition: Edition) => void;
}

/** Active edition (basic/pro). Defaults to basic so components render without a provider. */
export const EditionContext = createContext<EditionState>({
  edition: "basic",
  setEdition: () => {},
});

export function useEdition(): EditionState {
  return useContext(EditionContext);
}
