// Buttons you click in the terminal. They open /dev/tty themselves and read xterm mouse reports
// there, because after sudo has used the terminal Ink no longer gets key presses (the installer
// froze on "Open it now?"). Keys work too: a button's number, enter for the first, esc to cancel.
import { closeSync, openSync, readSync, writeSync } from "node:fs";

const PINK = "\x1b[38;2;255;61;154m";
const CYAN = "\x1b[38;2;46;230;255m";
const DIM = "\x1b[2m";
const RESET = "\x1b[0m";

/** The terminal's size, [rows, columns]. */
export function size(): [number, number] {
  const out = Bun.spawnSync(["sh", "-c", "stty size </dev/tty"]).stdout.toString().trim().split(/\s+/);
  const [rows, cols] = out.map(Number);
  return [rows || 24, cols || 80];
}

/** Splits *text* into lines no wider than *width*, breaking at spaces where it can. */
export function wrap(text: string, width: number): string[] {
  const out: string[] = [];
  for (const line of text.split(/\r?\n/)) {
    let rest = line;
    while (rest.length > width) {
      let cut = rest.lastIndexOf(" ", width);
      if (cut <= 0) cut = width;
      out.push(rest.slice(0, cut));
      rest = rest.slice(cut).trimStart();
    }
    out.push(rest);
  }
  return out;
}

export class NoTerminal extends Error {}

/**
 * Shows *lines* (the question and any hints), then a row of buttons from *labels()*. *pick(i)*
 * is called on each click or key; it returns a result to finish, or undefined to redraw the row.
 * Throws NoTerminal when there is no /dev/tty, and *cancel()* on esc / ctrl-c / q.
 */
export function clickRow<T>(
  lines: string[] | (() => string[]),
  labels: () => string[],
  pick: (i: number) => T | undefined,
  cancel: () => Error,
  wheel?: (down: boolean) => void,
): T {
  const text = typeof lines === "function" ? lines : () => lines;
  let shown = 0;
  let fd: number;
  try {
    fd = openSync("/dev/tty", "r+");
  } catch {
    throw new NoTerminal();
  }
  const say = (text: string) => writeSync(fd, text);
  const stty = (arg: string) => Bun.spawnSync(["sh", "-c", `stty ${arg} </dev/tty`]).stdout.toString().trim();
  const saved = stty("-g").replace(/[^\w:=-]/g, "");
  stty("raw -echo");
  let ranges: [number, number][] = [];
  const draw = () => {
    ranges = [];
    let line = "  ";
    let col = 3;
    labels().forEach((label, i) => {
      const text = ` ${label} `;
      ranges.push([col, col + text.length - 1]);
      line += `${i === 0 ? "\x1b[48;2;255;61;154m\x1b[30m" : "\x1b[7m"}\x1b[1m${text}${RESET}  `;
      col += text.length + 2;
    });
    say(`\r\x1b[2K${line}${DIM}← click a button${RESET}`);
  };
  try {
    const block = () => {
      if (shown) say(`\r\x1b[${shown}A\x1b[J`);
      const body = text();
      shown = body.length;
      say(`${body.join("\r\n")}\r\n`);
      draw();
    };
    say("\r\n\x1b[?25l");
    block();
    say("\x1b[?1000h\x1b[?1006h\x1b[6n");
    const buf = Buffer.alloc(256);
    let row = -1;
    let pending = "";
    for (;;) {
      const n = readSync(fd, buf, 0, buf.length, null);
      if (n <= 0) throw cancel();
      pending += buf.toString("latin1", 0, n);
      const pos = /\x1b\[(\d+);\d+R/.exec(pending);
      if (pos) {
        row = Number(pos[1]);
        pending = pending.replace(pos[0], "");
      }
      let chosen = -1;
      for (const m of pending.matchAll(/\x1b\[<(\d+);(\d+);(\d+)([Mm])/g)) {
        if (wheel && (m[1] === "64" || m[1] === "65")) {
          wheel(m[1] === "65");
          block();
        } else if (m[1] === "0" && m[4] === "M" && Number(m[3]) === row) {
          const x = Number(m[2]);
          chosen = ranges.findIndex(([from, to]) => x >= from && x <= to);
        }
      }
      pending = pending.replace(/\x1b\[<[\d;]*[Mm]/g, "");
      if (pending === "\x1b" || pending.includes("\x03") || pending.toLowerCase() === "q") throw cancel();
      if (pending.includes("\r") || pending.includes("\n")) chosen = 0;
      const digit = Number.parseInt(pending, 10);
      if (digit >= 1 && digit <= ranges.length) chosen = digit - 1;
      if (!pending.startsWith("\x1b")) pending = "";
      if (chosen < 0) continue;
      const result = pick(chosen);
      if (result !== undefined) {
        // Leave the question and the answer, not the buttons.
        say(`\r\x1b[${shown}A\x1b[J`);
        return result;
      }
      draw();
    }
  } finally {
    say("\x1b[?1006l\x1b[?1000l\x1b[?25h");
    stty(saved || "sane");
    closeSync(fd);
  }
}

/** The line left behind once a question is answered. */
export function answered(fd: (text: string) => void, question: string, answer: string): void {
  fd(`${PINK}? ${RESET}${question} ${CYAN}${answer}${RESET}\n`);
}

export const style = { PINK, CYAN, DIM, RESET };
