/**
 * LapisLazuli session summary for pi and Oh-My-Pi (install/OUTPUTS.md, Session extension).
 *
 * On session_start this runs `lapis-design-hook --plugin-version VERSION session-start`, the command the lazuli
 * SessionStart hook runs in Claude Code and Codex, and queues what it prints as context for the
 * next prompt. The host API is imported as a type only, so nothing is loaded at run time and the
 * same module works under pi and Oh-My-Pi, whose packages have different names; it uses only
 * `on("session_start")`, `exec`, and `sendMessage`, which both hosts provide. A missing CLI, a
 * failure, a timeout, or empty output adds nothing: the session always starts.
 */
import { spawn } from "node:child_process";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const COMMAND = "lapis-design-hook";
const ARGS = ["--plugin-version", "@LAPIS_VERSION@", "session-start"];
const TIMEOUT_MS = 10_000; // the SessionStart hook's timeout in plugins/lazuli/hooks/hooks.json

interface Context {
	cwd: string;
	hasUI?: boolean;
	ui?: { notify?: (message: string, level?: string) => void };
	sessionManager?: { getSessionId?: () => string };
}

function sessionSummary(event: object): Promise<string> {
	const { promise, resolve } = Promise.withResolvers<string>();
	let out = "";
	const child = spawn(COMMAND, ARGS, { stdio: ["pipe", "pipe", "ignore"] });
	const timer = setTimeout(() => child.kill(), TIMEOUT_MS);
	child.stdout.on("data", (chunk) => (out += chunk));
	child.stdin.on("error", () => {});
	child.on("error", () => resolve(JSON.stringify({
		systemMessage: "LapisLazuli hooks skipped: lapis-design-hook is unavailable; update the CLI and plugins together.",
	})));
	child.on("close", (code) => {
		clearTimeout(timer);
		resolve(code === 0 ? out.trim() : "");
	});
	child.stdin.end(JSON.stringify(event));
	return promise;
}

export default function lapisLazuliSessionStart(pi: ExtensionAPI): void {
	const fallback = crypto.randomUUID();
	pi.on("session_start", async (event, context) => {
		const ctx = context as Context;
		// pi also fires session_start when extensions reload, and the session already has the
		// summary then; Oh-My-Pi's event has no reason
		if ("reason" in event && event.reason === "reload") return;
		const summary = await sessionSummary({
			hook_event_name: "SessionStart", cwd: ctx.cwd,
			session_id: ctx.sessionManager?.getSessionId?.() || fallback,
		});
		if (!summary) return;
		// Version notices are JSON, not inventory context. Surface them without
		// sending a message that could request another agent turn.
		try {
			const notice = JSON.parse(summary);
			if (typeof notice.systemMessage === "string") {
				try {
					if (ctx.hasUI && ctx.ui?.notify) {
						ctx.ui.notify(notice.systemMessage, "info");
						return;
					}
				} catch {
					// A UI failure must not prevent startup or hide the notice.
				}
				process.stderr.write(`${notice.systemMessage}\n`);
				return;
			}
		} catch {
			// The normal inventory summary is plain text.
		}
		try {
			pi.sendMessage(
				{ customType: "lapis-lazuli-session", content: summary, display: false },
				{ deliverAs: "nextTurn" },
			);
		} catch {
			// a host without this delivery mode gets no summary; the skills say what to run by hand
		}
	});
}
