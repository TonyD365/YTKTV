// Builds one program per platform into dist/: ytktv-installer-<os>-<arch>[.exe].
//   bun build.ts            all platforms
//   bun build.ts darwin-arm64
import { $ } from "bun";

await $`bun notices.ts`;
await $`rm -rf dist`;
const TARGETS = ["darwin-arm64", "darwin-x64", "linux-x64", "linux-arm64", "windows-x64"];
const wanted = process.argv.slice(2);
for (const target of TARGETS.filter((t) => !wanted.length || wanted.includes(t))) {
  const out = `dist/ytktv-installer-${target}${target.startsWith("windows") ? ".exe" : ""}`;
  await $`bun build src/main.tsx --compile --minify --target=bun-${target} --outfile ${out}`;
  // The appended program breaks Bun's own signature on macOS; sign it again (ad hoc).
  if (target.startsWith("darwin") && process.platform === "darwin") await $`codesign --force -s - ${out}`;
  console.log(`built ${out}`);
}
