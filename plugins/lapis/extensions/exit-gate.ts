/**
 * LapisLazuli exit gate for pi and Oh-My-Pi (install/OUTPUTS.md, Session extension and packages).
 *
 * When the agent is about to stop, this runs `lapis-design hook stop`, the command the lapis plugin's
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
 */
import { spawn } from "node:child_process";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const COMMAND = "lapis-design";
const ARGS = ["hook", "stop"];
const TIMEOUT_MS = 60_000; // the Stop hook's timeout in plugins/lapis/hooks/hooks.json

interface Answer {
	decision?: string;
	reason?: string;
	systemMessage?: string;
}

// the parts of each host's context this file uses; both hosts provide them
interface Context {
	cwd: string;
	hasUI?: boolean;
	ui?: { notify?: (message: string, level?: string) => void };
	sessionManager?: { getSessionId?: () => string };
}

function ask(event: object): Promise<Answer> {
	const { promise, resolve } = Promise.withResolvers<Answer>();
	let out = "";
	const child = spawn(COMMAND, ARGS, { stdio: ["pipe", "pipe", "ignore"] });
	const timer = setTimeout(() => child.kill(), TIMEOUT_MS);
	child.stdout.on("data", (chunk) => (out += chunk));
	child.stdin.on("error", () => {});
	child.on("error", () => resolve({})); // the CLI is not installed or could not start
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
	const stop = async (ctx: Context): Promise<Answer> => {
		let session = fallback;
		try {
			session = ctx.sessionManager?.getSessionId?.() || fallback;
		} catch {
			// the fallback id keeps the count of this process together
		}
		const answer = await ask({ hook_event_name: "Stop", cwd: ctx.cwd, session_id: session });
		if (answer.systemMessage && ctx.hasUI) {
			try {
				ctx.ui?.notify?.(answer.systemMessage, "info");
			} catch {
				// a host without notifications shows nothing
			}
		}
		return answer;
	};
	// each host's typed overloads name only its own events, so the registration is cast once
	const on = pi.on.bind(pi) as unknown as (
		event: string,
		handler: (event: { outcome?: string }, ctx: Context) => unknown,
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
}
