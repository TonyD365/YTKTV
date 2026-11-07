// Writes src/notices.txt: the licenses of everything built into the installer program.
// Run by build.ts before compiling; `ytktv-installer --licenses` prints it.
import { existsSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const root = "node_modules";
const runtime = ["ink", "ink-spinner", "react"];
const seen = new Map<string, { version: string; license: string; text: string }>();

function add(name: string) {
  if (seen.has(name)) return;
  const dir = join(root, name);
  const pkg = JSON.parse(readFileSync(join(dir, "package.json"), "utf8"));
  const file = readdirSync(dir).find((f) => /^licen[cs]e/i.test(f));
  seen.set(name, { version: pkg.version, license: pkg.license ?? "", text: file ? readFileSync(join(dir, file), "utf8").trim() : "" });
  for (const dep of Object.keys(pkg.dependencies ?? {})) if (existsSync(join(root, dep))) add(dep);
}
runtime.forEach(add);

const head = `The YTKTV installer program

The installer's own code is under the YTKTV License, like YTKTV:
https://github.com/TonyD365/YTKTV/blob/main/LICENSE

It is built with Bun (https://bun.sh, MIT License). Bun includes JavaScriptCore from WebKit,
which is under the GNU Lesser General Public License 2.1 (LGPL-2.1). Its source code, as used
by Bun, is at https://github.com/oven-sh/WebKit, and the LGPL-2.1 is at
https://www.gnu.org/licenses/old-licenses/lgpl-2.1.html. You may replace or modify that
library under the terms of the LGPL; nothing in the YTKTV License restricts that.

It also includes these JavaScript packages, each under its own license:
`;
const list = [...seen].sort().map(([name, p]) => `- ${name} ${p.version} (${p.license})`).join("\n");
const texts = [...seen].sort().map(([name, p]) => `==== ${name} ${p.version} ====\n${p.text || p.license}`).join("\n\n");
writeFileSync("src/notices.txt", `${head}\n${list}\n\n${texts}\n`);
console.log(`notices: ${seen.size} packages`);
