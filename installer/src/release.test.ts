import { expect, test } from "bun:test";
import { type Release, assetFor, compareVersions, parseSums } from "./release";

const release: Release = {
  tag_name: "v4.1.2",
  assets: [
    "YTKTV-4.1.2-macos-universal.pkg",
    "YTKTV-Desk-4.1.2-macos-universal.pkg",
    "YTKTV-patch-4.1.1-4.1.2-macos-arm64.zip",
    "YTKTV-4.1.2-windows-x64-setup.exe",
  ].map((name) => ({ name, size: 1, browser_download_url: `https://dl.invalid/${name}` })),
};

test("picks the app's own file, never the Desk's or a patch", () => {
  expect(assetFor(release, "YTKTV", "macos-universal.pkg")?.name).toBe("YTKTV-4.1.2-macos-universal.pkg");
  expect(assetFor(release, "YTKTV-Desk", "macos-universal.pkg")?.name).toBe("YTKTV-Desk-4.1.2-macos-universal.pkg");
  expect(assetFor(release, "YTKTV-Desk", "windows-x64-setup.exe")).toBeUndefined();
});

test("reads SHA256SUMS in text and binary mode", () => {
  const a = "a".repeat(64);
  const b = "B".repeat(64);
  const sums = parseSums(`${a}  one.pkg\r\n${b} *two.exe\nnot a line\n`);
  expect(sums.get("one.pkg")).toBe(a);
  expect(sums.get("two.exe")).toBe("b".repeat(64));
});

test("compares versions by number", () => {
  expect(compareVersions("4.1.10", "4.1.9")).toBe(1);
  expect(compareVersions("v4.1.2", "4.1.2")).toBe(0);
  expect(compareVersions("4.0.0", "4.1")).toBe(-1);
});
