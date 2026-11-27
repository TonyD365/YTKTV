import { expect, test } from "bun:test";
import { generateKeyPairSync, sign } from "node:crypto";
import { type Release, UPDATE_KEYS, assetFor, compareVersions, parseSums, sumsSigned } from "./release";

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

test("SHA256SUMS counts only with a signature from a trusted key", () => {
  const { privateKey, publicKey } = generateKeyPairSync("ed25519");
  const raw = publicKey.export({ format: "der", type: "spki" }).subarray(12).toString("base64");
  const sums = `${"a".repeat(64)}  YTKTV.pkg\n`;
  const sig = sign(null, Buffer.from(sums), privateKey).toString("base64");
  expect(sumsSigned(sums, sig, [raw])).toBe(true);
  expect(sumsSigned(sums.replace("a", "b"), sig, [raw])).toBe(false); // changed checksums
  expect(sumsSigned(sums, sig)).toBe(false); // a key YTKTV does not trust
  expect(sumsSigned(sums, "not base64 at all", [raw])).toBe(false);
  expect(UPDATE_KEYS.every((k) => Buffer.from(k, "base64").length === 32)).toBe(true);
});
