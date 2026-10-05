/**
 * LapisLazuli exit gate and write guard for pi and Oh-My-Pi (install/OUTPUTS.md, Session extension and packages).
 *
 * When the agent is about to stop, this runs `lapis-design-hook --plugin-version VERSION stop`, the command the lapis plugin's
 * Stop hook runs in Claude Code and Codex, and passes on what it decides: the next step of the procedure
 * that `lapis-design next` still asks for (it continues the agent only when LAPIS_UNATTENDED=1 and never
 * more than three times in a row for one step or fifteen in a session), or a one-line notice for a
 * person. The rules live in the CLI; this file only translates its answer into each host's event.
 *
 * Oh-My-Pi fires `session_stop` and takes `{ decision: "block", reason }`; pi fires
 * `agent_before_settle` and takes a custom message with `continue: true`. Each host never fires the
 * other's event, so both are registered. The host API is imported as a type only, and the CLI is started
 * with node's child_process, which both hosts provide. A missing CLI, a failure, a timeout, or output
 * that is not the expected JSON lets the agent stop.
 *
 * Before a write or edit tool runs, both hosts fire `tool_call`, and this runs `lapis-design-hook --plugin-version VERSION pre-write`,
 * the command the lapis plugin's PreToolUse hook runs in Claude Code and Codex. Its refusal (only when
 * LAPIS_UNATTENDED=1, while the brief, references, or plan of a create run is still owed) becomes
 * `{ block: true, reason }`. Both hosts block the tool when a `tool_call` handler fails or runs past its
 * budget (30 seconds in Oh-My-Pi), so this handler answers within 20 and turns every failure into no answer.
 */
import { spawn } from "node:child_process";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const COMMAND = "lapis-design-hook";
const VERSION_ARGS = ["--plugin-version", "0.2.0"];
const STOP_ARGS = [...VERSION_ARGS, "stop"];
const WRITE_ARGS = [...VERSION_ARGS, "pre-write"];
const TIMEOUT_MS = 60_000; // the Stop hook's timeout in plugins/lapis/hooks/hooks.json
const WRITE_TIMEOUT_MS = 20_000; // inside the hosts' 30 second budget for a tool_call handler
const WRITE_TOOLS: Record<string, true> = { write: true, edit: true, multiedit: true, multi_edit: true, ast_edit: true, apply_patch: true };

interface Answer {
	decision?: string;
	reason?: string;
	systemMessage?: string;
	hookSpecificOutput?: { permissionDecision?: string; permissionDecisionReason?: string };
}

// the parts of each host's context this file uses; both hosts provide them
interface Context {
	cwd: string;
	hasUI?: boolean;
	ui?: { notify?: (message: string, level?: string) => void };
	sessionManager?: { getSessionId?: () => string };
}

function ask(args: string[], timeoutMs: number, event: object): Promise<Answer> {
	const { promise, resolve } = Promise.withResolvers<Answer>();
	let out = "";
	const child = spawn(COMMAND, args, { stdio: ["pipe", "pipe", "ignore"] });
	const timer = setTimeout(() => child.kill(), timeoutMs);
	child.stdout.on("data", (chunk) => (out += chunk));
	child.stdin.on("error", () => {});
	child.on("error", () => resolve({ systemMessage: "LapisLazuli hooks skipped: lapis-design-hook is unavailable; update the CLI and plugins together." }));
	child.on("close", (code) => {
		clearTimeout(timer);
		try {
			resolve(code === 0 ? (JSON.parse(out) as Answer) : {});
		} catch {
			resolve({}); // no output means nothing to say
		}
	});
	child.stdin.end(JSON.stringify(event));
	return promise;
}

export default function lapisLazuliExitGate(pi: ExtensionAPI): void {
	const fallback = crypto.randomUUID(); // one id per session when the host does not give one
	const notices = new Set<string>();
	const notify = (answer: Answer, ctx: Context): void => {
		const message = answer.systemMessage;
		if (!message) return;
		let session = fallback;
		try {
			session = ctx.sessionManager?.getSessionId?.() || fallback;
		} catch {
			// Session-manager failures do not change whether the agent may stop.
		}
		const key = `${session}:${message}`;
		if (message.startsWith("LapisLazuli hook") && notices.has(key)) return;
		notices.add(key);
		try {
			if (ctx.hasUI && ctx.ui?.notify) {
				ctx.ui.notify(message, "info");
				return;
			}
		} catch {
			// Headless hosts and unavailable UI methods still get one visible line.
		}
		process.stderr.write(`${message}\n`);
	};
	const stop = async (ctx: Context): Promise<Answer> => {
		let session = fallback;
		try {
			session = ctx.sessionManager?.getSessionId?.() || fallback;
		} catch {
			// the fallback id keeps the count of this process together
		}
		const answer = await ask(STOP_ARGS, TIMEOUT_MS, { hook_event_name: "Stop", cwd: ctx.cwd, session_id: session });
		notify(answer, ctx);
		return answer;
	};
	// each host's typed overloads name only its own events, so the registration is cast once
	const on = pi.on.bind(pi) as unknown as (
		event: string,
		handler: (event: { outcome?: string; toolName?: string; input?: unknown }, ctx: Context) => unknown,
	) => void;

	on("session_stop", async (_event, ctx) => {
		const answer = await stop(ctx);
		if (answer.decision === "block" && answer.reason) return { decision: "block", reason: answer.reason };
	});

	on("agent_before_settle", async (event, ctx) => {
		if (event.outcome !== "completed") return;
		const answer = await stop(ctx);
		if (answer.decision !== "block" || !answer.reason) return;
		return {
			entries: [{ type: "custom_message", customType: "lapis-lazuli-gate", content: answer.reason, display: false }],
			continue: true,
		};
	});

	on("tool_call", async (event, ctx) => {
		try {
			if (!Object.hasOwn(WRITE_TOOLS, String(event.toolName).toLowerCase())) return;
			const answer = await ask(WRITE_ARGS, WRITE_TIMEOUT_MS, {
				hook_event_name: "PreToolUse",
				cwd: ctx.cwd,
				tool_name: event.toolName,
				tool_input: event.input,
				session_id: ctx.sessionManager?.getSessionId?.() || fallback,
			});
			notify(answer, ctx);
			const refusal = answer.hookSpecificOutput;
			if (refusal?.permissionDecision === "deny" && refusal.permissionDecisionReason) {
				return { block: true, reason: refusal.permissionDecisionReason };
			}
		} catch {
			// a failure here would block the tool in the host: no answer lets the write go on
		}
	});
}
