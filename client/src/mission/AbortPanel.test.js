/*
 * AbortPanel, rendered.
 *
 * This is the panel an operator reaches for when something has gone wrong, so
 * the three properties it was written to have are worth checking against a real
 * DOM rather than by reading the source:
 *
 *   1. It never shows success for a command that was not transmitted.
 *   2. It shows WHICH aircraft acknowledged.
 *   3. It does not fire on one click.
 *
 * The last one is the reason for the test at the bottom. Two-step arm-then-
 * confirm is easy to write and easy to break -- a refactor that hoists the
 * fetch out of the confirm branch looks harmless and turns a misclick during a
 * nominal mission into a mission abort.
 */
import React from "react"
import { render, screen, waitFor, fireEvent } from "@testing-library/react"

import AbortPanel from "./AbortPanel"

const NO_RADIO = {
	state: "NO_RADIO", configured: false, command: null,
	acknowledged: [], missing: [], drones: [1, 2, 3], frames_sent: 0,
}

const SENDING = {
	state: "SENDING", configured: true, command: "ABORT",
	acknowledged: [1], missing: [2, 3], drones: [1, 2, 3],
	frames_sent: 12, elapsed_s: 1.4,
}

const mockStatus = body =>
	jest.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve(body) }))

afterEach(() => {
	jest.restoreAllMocks()
})

test("renders at all", async () => {
	global.fetch = mockStatus(NO_RADIO)
	const { container } = render(<AbortPanel pollMs={100000} />)
	await waitFor(() => expect(container).not.toBeEmptyDOMElement())
	expect(screen.getByText(/SAFETY/)).toBeInTheDocument()
})

test("with no radio it says NOT IMPLEMENTED, not OK", async () => {
	/* A green tick over a dead radio is worse than no button at all: it stops
	 * someone reaching for the safety pilot's transmitter, which is the one
	 * thing that would have worked. */
	global.fetch = mockStatus(NO_RADIO)
	render(<AbortPanel pollMs={100000} />)
	await waitFor(() =>
		expect(screen.getByText(/NOT IMPLEMENTED/)).toBeInTheDocument())
	expect(screen.getByText(/transmitter/)).toBeInTheDocument()
})

test("shows per-aircraft acknowledgement, not just 'sent'", async () => {
	/* On a lossy 868 MHz link "abort sent" and "abort received" are different
	 * claims, and only the second means an aircraft is coming home. */
	global.fetch = mockStatus(SENDING)
	render(<AbortPanel pollMs={100000} />)
	await waitFor(() => expect(screen.getByText(/D1 ACK/)).toBeInTheDocument())
	expect(screen.getByText(/D2 —/)).toBeInTheDocument()
	expect(screen.getByText(/D3 —/)).toBeInTheDocument()
})

test("both 8.19 controls are present", async () => {
	global.fetch = mockStatus(NO_RADIO)
	render(<AbortPanel pollMs={100000} />)
	await waitFor(() => expect(screen.getByText("ABORT")).toBeInTheDocument())
	expect(screen.getByText("RECALL")).toBeInTheDocument()
})

test("one click ARMS but does not transmit; the second click transmits", async () => {
	const calls = []
	global.fetch = jest.fn(url => {
		calls.push(String(url))
		return Promise.resolve({ ok: true, json: () => Promise.resolve(NO_RADIO) })
	})
	render(<AbortPanel pollMs={100000} />)
	await waitFor(() => expect(screen.getByText("ABORT")).toBeInTheDocument())

	fireEvent.click(screen.getByText("ABORT"))
	// Armed, and asking for confirmation -- nothing sent.
	await waitFor(() =>
		expect(screen.getByText("CONFIRM ABORT")).toBeInTheDocument())
	expect(calls.filter(u => u.includes("/api/safety/abort"))).toHaveLength(0)

	fireEvent.click(screen.getByText("CONFIRM ABORT"))
	await waitFor(() =>
		expect(calls.filter(u => u.includes("/api/safety/abort"))).toHaveLength(1))
})

test("a backend that cannot be reached is reported, not hidden", async () => {
	global.fetch = jest.fn(() => Promise.reject(new Error("ECONNREFUSED")))
	render(<AbortPanel pollMs={100000} />)
	await waitFor(() =>
		expect(screen.getByText(/backend unreachable/i)).toBeInTheDocument())
})
