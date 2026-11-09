// The installer's screens, drawn with Ink like Claude Code's. Each prompt is its own short
// render that leaves a one-line answer behind, so the flow in main.tsx reads top to bottom.
import { Box, Text, render, useApp, useInput, useStdout } from "ink";
import Spinner from "ink-spinner";
import { NoTerminal, answered, clickRow, size, style, wrap } from "./buttons";
import { type ReactElement, type ReactNode, useEffect, useState } from "react";

export const PINK = "#ff3d9a";
export const CYAN = "#2ee6ff";

/** Renders *element*, which calls `done(value)` once; resolves with that value. */
function ask<T>(element: (done: (value: T) => void) => ReactElement): Promise<T> {
  return new Promise((resolve) => {
    let result: T;
    // Hold the program open while it waits for keys.
    const keepAlive = setInterval(() => {}, 1 << 30);
    const instance = render(
      element((value) => {
        result = value;
      }),
      { exitOnCtrlC: false },
    );
    instance.waitUntilExit().then(() => {
      clearInterval(keepAlive);
      resolve(result);
    });
  });
}

/** Prints *element* once and leaves it on the screen. */
export async function print(element: ReactElement): Promise<void> {
  await close(render(element));
}

/** Unmounts and lets Ink write its last frame (waitUntilExit does not resolve after unmount). */
function close(instance: { unmount: () => void }): Promise<void> {
  instance.unmount();
  return new Promise((resolve) => setTimeout(resolve, 0));
}

export class Cancelled extends Error {}

const say = (text: string) => process.stdout.write(text);

/** The options' hints, one dim line each, shown above the buttons. */
function hints(options: Option[]): string[] {
  return options.filter((o) => o.hint).map((o) => `  ${o.label.padEnd(14)}${style.DIM}${o.hint}${style.RESET}`);
}

function useCancel(onCancel: () => void) {
  useInput((input, key) => {
    if (key.escape || (key.ctrl && input === "c") || input === "q") onCancel();
  });
}

export function Header({ version, system }: { version: string; system: string }) {
  return (
    <Box borderStyle="round" borderColor={PINK} paddingX={2} flexDirection="column" marginTop={1} alignSelf="flex-start">
      <Text>
        <Text color={PINK} bold>
          ♪ YTKTV
        </Text>
        <Text bold> Installer</Text>
      </Text>
      <Text dimColor>
        {version} · {system}
      </Text>
    </Box>
  );
}

export function Done({ text }: { text: string }) {
  return (
    <Text>
      <Text color="green">✔ </Text>
      {text}
    </Text>
  );
}

export function Note({ text }: { text: string }) {
  return (
    <Text>
      <Text color={CYAN}>ℹ </Text>
      {text}
    </Text>
  );
}

export function Failed({ text }: { text: string }) {
  return (
    <Text>
      <Text color="red">✘ </Text>
      {text}
    </Text>
  );
}

/** A page of text in a rounded box; the first line is its title. */
export function Page({ text, color = CYAN }: { text: string; color?: string }) {
  const [title, ...lines] = text.trim().split(/\r?\n/);
  return (
    <Box borderStyle="round" borderColor={color} paddingX={2} flexDirection="column" marginTop={1}>
      <Text color={color} bold>
        {title}
      </Text>
      {lines.map((line, i) =>
        /^[^\s-]/.test(line) ? (
          <Text key={i} bold>
            {line}
          </Text>
        ) : (
          <Text key={i}>{line.replace(/^- /, "• ")}</Text>
        ),
      )}
    </Box>
  );
}

export interface Option {
  label: string;
  hint?: string;
}

function OptionRow({ option, active, mark }: { option: Option; active: boolean; mark?: ReactNode }) {
  return (
    <Text>
      <Text color={PINK}>{active ? "❯ " : "  "}</Text>
      {mark !== undefined && <Text>{mark} </Text>}
      <Text bold={active} color={active ? "white" : undefined}>
        {option.label.padEnd(14)}
      </Text>
      <Text dimColor> {option.hint ?? ""}</Text>
    </Text>
  );
}

function Select({ question, options, done }: { question: string; options: Option[]; done: (i: number) => void }) {
  const { exit } = useApp();
  const [index, setIndex] = useState(0);
  const [chosen, setChosen] = useState<number | null>(null);
  useEffect(() => {
    if (chosen !== null) exit();
  }, [chosen, exit]);
  useCancel(() => {
    done(-1);
    setChosen(-1);
  });
  useInput((_input, key) => {
    if (chosen !== null) return;
    if (key.upArrow) setIndex((index + options.length - 1) % options.length);
    if (key.downArrow || key.tab) setIndex((index + 1) % options.length);
    if (key.return) {
      done(index);
      setChosen(index);
    }
  });
  if (chosen !== null)
    return chosen < 0 ? (
      <Failed text={`${question} · cancelled`} />
    ) : (
      <Text>
        <Text color={PINK}>? </Text>
        {question} <Text color={CYAN}>{options[chosen].label}</Text>
      </Text>
    );
  return (
    <Box flexDirection="column" marginTop={1}>
      <Text bold>
        <Text color={PINK}>? </Text>
        {question}
      </Text>
      {options.map((option, i) => (
        <OptionRow key={option.label} option={option} active={i === index} />
      ))}
      <Text dimColor>↑/↓ move · enter choose · esc cancel</Text>
    </Box>
  );
}

/** An arrow-key menu; resolves with the chosen index, throws Cancelled on esc / q. */
export async function select(question: string, options: Option[]): Promise<number> {
  if (process.platform !== "win32") {
    try {
      const i = clickRow(
        [`${style.PINK}? ${style.RESET}\x1b[1m${question}${style.RESET}`, ...hints(options)],
        () => options.map((o) => o.label),
        (i) => i,
        () => new Cancelled(),
      );
      answered(say, question, options[i].label);
      return i;
    } catch (error) {
      if (!(error instanceof NoTerminal)) throw error;
    }
  }
  const chosen = await ask<number>((done) => <Select question={question} options={options} done={done} />);
  if (chosen < 0) throw new Cancelled();
  return chosen;
}

function Checklist({
  question,
  options,
  initial,
  done,
}: {
  question: string;
  options: Option[];
  initial: boolean[];
  done: (ticks: boolean[] | null) => void;
}) {
  const { exit } = useApp();
  const [index, setIndex] = useState(0);
  const [ticks, setTicks] = useState(initial);
  const [finished, setFinished] = useState<boolean | null>(null);
  const [warn, setWarn] = useState(false);
  useEffect(() => {
    if (finished !== null) exit();
  }, [finished, exit]);
  useCancel(() => {
    done(null);
    setFinished(false);
  });
  useInput((input, key) => {
    if (finished !== null) return;
    if (key.upArrow) setIndex((index + options.length - 1) % options.length);
    if (key.downArrow || key.tab) setIndex((index + 1) % options.length);
    if (input === " ") setTicks(ticks.map((t, i) => (i === index ? !t : t)));
    if (key.return) {
      if (!ticks.includes(true)) return setWarn(true);
      done(ticks);
      setFinished(true);
    }
  });
  if (finished === false) return <Failed text={`${question} · cancelled`} />;
  if (finished)
    return (
      <Text>
        <Text color={PINK}>? </Text>
        {question}{" "}
        <Text color={CYAN}>
          {options
            .filter((_, i) => ticks[i])
            .map((o) => o.label)
            .join(" + ")}
        </Text>
      </Text>
    );
  return (
    <Box flexDirection="column" marginTop={1}>
      <Text bold>
        <Text color={PINK}>? </Text>
        {question}
      </Text>
      {options.map((option, i) => (
        <OptionRow
          key={option.label}
          option={option}
          active={i === index}
          mark={ticks[i] ? <Text color="green">◉</Text> : "◯"}
        />
      ))}
      <Text dimColor>↑/↓ move · space tick · enter go on · esc cancel</Text>
      {warn && <Text color="yellow">Tick at least one.</Text>}
    </Box>
  );
}

/** Checkboxes; resolves with the ticks, throws Cancelled on esc / q. */
export async function checklist(question: string, options: Option[], initial: boolean[]): Promise<boolean[]> {
  if (process.platform !== "win32") {
    const ticks = [...initial];
    try {
      clickRow(
        [`${style.PINK}? ${style.RESET}\x1b[1m${question}${style.RESET} ${style.DIM}(click to tick, then Continue)${style.RESET}`, ...hints(options)],
        () => [...options.map((o, i) => `${ticks[i] ? "◉" : "◯"} ${o.label}`), "Continue →"],
        (i) => {
          if (i < options.length) ticks[i] = !ticks[i];
          else if (ticks.includes(true)) return true;
          return undefined;
        },
        () => new Cancelled(),
      );
      answered(say, question, options.filter((_, i) => ticks[i]).map((o) => o.label).join(" + "));
      return ticks;
    } catch (error) {
      if (!(error instanceof NoTerminal)) throw error;
    }
  }
  const ticks = await ask<boolean[] | null>((done) => (
    <Checklist question={question} options={options} initial={initial} done={done} />
  ));
  if (!ticks) throw new Cancelled();
  return ticks;
}

function Pager({ title, text, done }: { title: string; text: string; done: (v: null) => void }) {
  const { exit } = useApp();
  const { stdout } = useStdout();
  const lines = text.split(/\r?\n/);
  const height = Math.max(5, (stdout.rows || 24) - 7);
  const [top, setTop] = useState(0);
  const [closed, setClosed] = useState(false);
  const last = Math.max(0, lines.length - height);
  useEffect(() => {
    if (closed) exit();
  }, [closed, exit]);
  useInput((input, key) => {
    if (closed) return;
    if (key.upArrow) setTop(Math.max(0, top - 1));
    if (key.downArrow || key.return) setTop(Math.min(last, top + 1));
    if (key.pageUp) setTop(Math.max(0, top - height));
    if (key.pageDown || input === " ") setTop(Math.min(last, top + height));
    if (input === "q" || key.escape) {
      done(null);
      setClosed(true);
    }
  });
  if (closed) return <Done text={`Read the ${title}`} />;
  return (
    <Box flexDirection="column" borderStyle="round" borderColor={CYAN} paddingX={2} marginTop={1}>
      <Text color={CYAN} bold>
        {title}
      </Text>
      {lines.slice(top, top + height).map((line, i) => (
        <Text key={top + i}>{line || " "}</Text>
      ))}
      <Text dimColor>
        ↑/↓ scroll · space next page · q close · {Math.min(100, Math.round(((top + height) / lines.length) * 100))}%
      </Text>
    </Box>
  );
}

export async function page(title: string, text: string): Promise<null> {
  if (process.platform !== "win32") {
    try {
      const [rows, cols] = size();
      const lines = wrap(text, Math.max(20, cols - 4));
      const height = Math.max(5, rows - 6);
      const last = Math.max(0, lines.length - height);
      let top = 0;
      const percent = () => Math.min(100, Math.round(((top + height) / lines.length) * 100));
      clickRow(
        () => [
          `${style.CYAN}\x1b[1m${title}${style.RESET} ${style.DIM}· scroll with the mouse wheel · ${percent()}%${style.RESET}`,
          ...Array.from({ length: Math.min(height, lines.length) }, (_, i) => `  ${lines[top + i] ?? ""}`),
        ],
        () => ["Done reading", "Page down ↓", "Page up ↑"],
        (i) => {
          if (i === 0) return true;
          top = i === 1 ? Math.min(last, top + height) : Math.max(0, top - height);
          return undefined;
        },
        () => new Cancelled(),
        (down) => {
          top = down ? Math.min(last, top + 3) : Math.max(0, top - 3);
        },
      );
      say(`\x1b[32m✔${style.RESET} Read the ${title}\n`);
      return null;
    } catch (error) {
      if (!(error instanceof NoTerminal)) throw error;
    }
  }
  return ask<null>((done) => <Pager title={title} text={text} done={done} />);
}

function Busy({ text }: { text: string }) {
  return (
    <Text>
      <Text color={PINK}>
        <Spinner type="dots" />
      </Text>{" "}
      {text}
    </Text>
  );
}

/** Shows a spinner while *work* runs, then ✔ *doneText* (or ✘ and rethrows). */
export async function task<T>(text: string, work: () => Promise<T>, doneText?: (value: T) => string): Promise<T> {
  const instance = render(<Busy text={text} />);
  try {
    const value = await work();
    instance.rerender(<Done text={doneText ? doneText(value) : text.replace(/…$/, "")} />);
    return value;
  } catch (error) {
    instance.rerender(<Failed text={text.replace(/…$/, "")} />);
    throw error;
  } finally {
    await close(instance);
  }
}

const mb = (bytes: number) => (bytes / 1048576).toFixed(bytes >= 104857600 ? 0 : 1);

function Bar({ name, done, total, speed, attempt }: { name: string; done: number; total: number; speed: number; attempt: number }) {
  const width = 30;
  const share = total ? Math.min(1, done / total) : 0;
  const filled = Math.round(share * width);
  const left = speed > 0 && total ? Math.round((total - done) / speed) : -1;
  const eta = left < 0 ? "--:--" : `${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}`;
  return (
    <Box flexDirection="column">
      <Text>
        <Text color={PINK}>
          <Spinner type="dots" />
        </Text>{" "}
        Downloading {name}
        {attempt > 1 && <Text color="yellow"> (try {attempt} of 5, going on where it stopped)</Text>}
      </Text>
      <Text>
        {"  "}
        <Text color={PINK}>{"█".repeat(filled)}</Text>
        <Text dimColor>{"░".repeat(width - filled)}</Text> {String(Math.round(share * 100)).padStart(3)}%{"  "}
        <Text dimColor>
          {mb(done)} / {mb(total)} MB · {mb(speed)} MB/s · {eta} left
        </Text>
      </Text>
    </Box>
  );
}

export interface Progress {
  done: number;
  total: number;
  speed: number;
  attempt: number;
}

/** A download progress bar; *work* gets a function to report progress with. */
export async function progress(name: string, work: (update: (p: Progress) => void) => Promise<void>): Promise<void> {
  const instance = render(<Bar name={name} done={0} total={0} speed={0} attempt={1} />);
  let last = 0;
  try {
    await work((p) => {
      const now = Date.now();
      if (now - last < 100 && p.done < p.total) return;
      last = now;
      instance.rerender(<Bar name={name} {...p} />);
    });
    instance.rerender(<Done text={`Downloaded ${name}`} />);
  } catch (error) {
    instance.rerender(<Failed text={`Could not download ${name}`} />);
    throw error;
  } finally {
    await close(instance);
  }
}
