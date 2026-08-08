import { describe, expect, it } from "vitest";
import { parseLineImportText } from "./lineImportParsing";

describe("parseLineImportText", () => {
  it("parses a single well-formed line", () => {
    const entries = parseLineImportText("Zack Wheeler, 6.5, -115, -105");
    expect(entries).toEqual([
      {
        player_name: "Zack Wheeler",
        line: 6.5,
        over_price: -115,
        under_price: -105,
      },
    ]);
  });

  it("treats prices as optional", () => {
    const entries = parseLineImportText("Gerrit Cole, 7.5");
    expect(entries).toEqual([
      {
        player_name: "Gerrit Cole",
        line: 7.5,
        over_price: null,
        under_price: null,
      },
    ]);
  });

  it("parses multiple lines", () => {
    const entries = parseLineImportText(
      "Zack Wheeler, 6.5, -115, -105\nGerrit Cole, 7.5",
    );
    expect(entries.map((e) => e.player_name)).toEqual([
      "Zack Wheeler",
      "Gerrit Cole",
    ]);
  });

  it("skips blank lines", () => {
    const entries = parseLineImportText(
      "Zack Wheeler, 6.5\n\n\nGerrit Cole, 7.5",
    );
    expect(entries).toHaveLength(2);
  });

  it("drops a row with no player name", () => {
    const entries = parseLineImportText(", 6.5, -110\nGerrit Cole, 7.5");
    expect(entries).toEqual([
      {
        player_name: "Gerrit Cole",
        line: 7.5,
        over_price: null,
        under_price: null,
      },
    ]);
  });

  it("drops a row with a non-numeric line value", () => {
    const entries = parseLineImportText(
      "Zack Wheeler, not-a-number\nGerrit Cole, 7.5",
    );
    expect(entries).toEqual([
      {
        player_name: "Gerrit Cole",
        line: 7.5,
        over_price: null,
        under_price: null,
      },
    ]);
  });

  it("returns an empty array for empty input", () => {
    expect(parseLineImportText("")).toEqual([]);
    expect(parseLineImportText("   \n  \n")).toEqual([]);
  });
});
