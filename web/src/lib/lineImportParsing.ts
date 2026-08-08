import type { LineImportEntryIn } from "./types";

/** One entry per line: "Player Name, line, over_price, under_price" --
 * over/under price are optional. Deliberately simple (not full CSV
 * quoting/escaping) since player names never contain commas. */
export function parseLineImportText(text: string): LineImportEntryIn[] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0)
    .map((line) => {
      const parts = line.split(",").map((p) => p.trim());
      const [playerName, lineValue, overPrice, underPrice] = parts;
      return {
        player_name: playerName ?? "",
        line: Number(lineValue),
        over_price:
          overPrice && overPrice.length > 0 ? Number(overPrice) : null,
        under_price:
          underPrice && underPrice.length > 0 ? Number(underPrice) : null,
      };
    })
    .filter(
      (entry) => entry.player_name.length > 0 && !Number.isNaN(entry.line),
    );
}
