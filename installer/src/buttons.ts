// Buttons you click in the terminal. They open /dev/tty themselves and read xterm mouse reports
// there, because after sudo has used the terminal Ink no longer gets key presses (the installer
// froze on "Open it now?"). Keys work too: a button's number, enter for the first, esc to cancel.
import { closeSync, openSync, readSync, writeSync } from "node:fs";

const PINK = "\x1b[38;2;255;61;154m";
const CYAN = "\x1b[38;2;46;230;255m";
const DIM = "\x1b[2m";
const RESET = "\x1b[0m";

export class NoTerminal extends Error {}

/**
 * Shows *lines* (the question and any hints), then a row of buttons from *labels()*. *pick(i)*
 * is called on each click or key; it returns a result to finish, or undefined to redraw the row.
 * Throws NoTerminal when there is no /dev/tty, and *cancel()* on esc / ctrl-c / q.
 */
export function clickRow<T>(
  lines: string[],
  labels: () => string[],
  pick: (i: number) => T | undefined,
  cancel: () => Error,
): T {
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
    say(`\r\n${lines.join("\r\n")}\r\n\x1b[?25l`);
    draw();
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
        if (m[1] === "0" && m[4] === "M" && Number(m[3]) === row) {
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
        say(`\r\x1b[2K\x1b[${lines.length}A\r\x1b[J`);
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
