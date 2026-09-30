/**
 * LapisLazuli session summary for pi and Oh-My-Pi (install/OUTPUTS.md, Session extension).
 *
 * On session_start this runs `lapis-design hook session-start`, the command the lazuli
 * SessionStart hook runs in Claude Code and Codex, and queues what it prints as context for the
 * next prompt. The host API is imported as a type only, so nothing is loaded at run time and the
 * same module works under pi and Oh-My-Pi, whose packages have different names; it uses only
 * `on("session_start")`, `exec`, and `sendMessage`, which both hosts provide. A missing CLI, a
 * failure, a timeout, or empty output adds nothing: the session always starts.
 */
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const COMMAND = "lapis-design";
const ARGS = ["hook", "session-start"];
const TIMEOUT_MS = 10_000; // the SessionStart hook's timeout in plugins/lazuli/hooks/hooks.json

async function sessionSummary(pi: ExtensionAPI): Promise<string> {
	try {
		const result = await pi.exec(COMMAND, ARGS, { timeout: TIMEOUT_MS });
		return result.code === 0 && !result.killed ? result.stdout.trim() : "";
	} catch {
		return ""; // the CLI is not installed or could not start
	}
}

export default function lapisLazuliSessionStart(pi: ExtensionAPI): void {
	pi.on("session_start", async (event) => {
		// pi also fires session_start when extensions reload, and the session already has the
		// summary then; Oh-My-Pi's event has no reason
		if ("reason" in event && event.reason === "reload") return;
		const summary = await sessionSummary(pi);
		if (!summary) return;
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
