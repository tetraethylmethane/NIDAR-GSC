/*
 * The first test in this repo that RENDERS anything.
 *
 * Everything in client/src/mission was written, compiled, and shipped without
 * a single component ever being mounted. "It builds" says the syntax is valid;
 * it says nothing about whether the rule 8.14 displays put numbers on a screen.
 * These tests mount MissionStatus and read the resulting DOM.
 *
 * Rule 8.14 requires the GCS to display, at minimum:
 *   1 mission status        2 live camera feed per drone   3 drone position
 *   4 drone telemetry       5 detected survivor locations   6 delivery status
 *   7 comms and system health                               8 mission progress
 *
 * MissionStatus is responsible for 1, 4, 6, 7 and 8. Each is asserted here as
 * visible text, because a jury looks at a screen, not at a JSON payload.
 */
import React from "react"
import { render, screen } from "@testing-library/react"

import MissionStatus from "./MissionStatus"
import { EMPTY } from "./useFleet"

const fleet = {
	...EMPTY,
	vehicles: {
		1: { mode: "AUTO", gnss_fix: "RTK_FIXED", battery_pct: 74, health: "OK" },
		2: { mode: "AUTO", gnss_fix: "RTK_FLOAT", battery_pct: 61, health: "STALE" },
		3: { mode: "GUIDED", gnss_fix: "3D", battery_pct: 55, health: "OK" },
	},
	phases: { 1: "SEARCH", 2: "SEARCH", 3: "DELIVER" },
	survivors: { 1: { fix: "RTK_FIXED" }, 2: { fix: "3D" } },
	// CONFIRMED, not DELIVERED -- these are the states in fleet.py's ladder
	// (UNASSIGNED, ASSIGNED, EN_ROUTE, RELEASED, CONFIRMED, FAILED). A test
	// fixture that invents a state name passes through the `|| state` fallback
	// and proves nothing about the mapping.
	deliveries: { 1: { state: "CONFIRMED" } },
	progress: {
		...EMPTY.progress,
		found: 2, expected: 10, delivered: 1, elapsed: "4:12",
		bonus_window_s: 288, drones_ok: 2, drones_total: 3, rtk_fixed: 1,
	},
	warnings: ["survivor 2 tagged without RTK (3D)"],
}

test("renders at all", () => {
	const { container } = render(<MissionStatus fleet={fleet} online />)
	expect(container).not.toBeEmptyDOMElement()
})

test("8.14 item 8 — consolidated mission progress is on screen", () => {
	render(<MissionStatus fleet={fleet} online />)
	expect(screen.getByText("2/10")).toBeInTheDocument()      // survivors found
	expect(screen.getByText("1/10")).toBeInTheDocument()      // kits delivered
	expect(screen.getByText("4:12")).toBeInTheDocument()      // elapsed
})

test("8.14 item 7 — comms and system health, per drone", () => {
	render(<MissionStatus fleet={fleet} online />)
	expect(screen.getByText(/drones 2\/3 healthy/)).toBeInTheDocument()
	expect(screen.getByText(/RTK fixed 1\/3/)).toBeInTheDocument()
	// Drone 2 is stale; that has to be visible, not merely present in state.
	expect(screen.getByText(/STALE/)).toBeInTheDocument()
})

test("8.14 items 1 and 4 — per-drone phase, mode, fix and battery", () => {
	render(<MissionStatus fleet={fleet} online />)
	expect(screen.getByText(/D1 SEARCH · AUTO/)).toBeInTheDocument()
	expect(screen.getByText(/D3 DELIVER · GUIDED/)).toBeInTheDocument()
	expect(screen.getByText(/74%/)).toBeInTheDocument()
})

test("8.14 item 6 — delivery state per survivor", () => {
	render(<MissionStatus fleet={fleet} online />)
	expect(screen.getByText(/S1/)).toBeInTheDocument()
	expect(screen.getByText(/S2/)).toBeInTheDocument()
	expect(screen.getByText("delivered")).toBeInTheDocument()      // survivor 1
	// Survivor 2 has no delivery record and must read as not assigned rather
	// than silently absent -- an undelivered survivor is ~100 points.
	expect(screen.getByText("not assigned")).toBeInTheDocument()
})

test("a non-RTK survivor tag raises a VISIBLE warning", () => {
	/* A 3D fix is metres of error against a 1 m scoring zone. It has to be
	 * obvious while there is still time to re-acquire, not buried in a log. */
	render(<MissionStatus fleet={fleet} online />)
	expect(screen.getByText(/tagged without RTK/)).toBeInTheDocument()
})

test("a stale display announces itself when the backend is unreachable", () => {
	/* Keeping the last good snapshot on screen is right -- a blank map mid
	 * mission is worse than a stale one -- but ONLY if the staleness shows.
	 * Otherwise the operator flies on numbers that stopped updating. */
	render(<MissionStatus fleet={fleet} online={false} />)
	expect(
		screen.getByText("GCS BACKEND UNREACHABLE — display is stale")
	).toBeInTheDocument()
})

test("no stale banner when the backend is reachable", () => {
	render(<MissionStatus fleet={fleet} online />)
	expect(screen.queryByText(/UNREACHABLE/)).not.toBeInTheDocument()
})

test("renders with an empty fleet without throwing", () => {
	/* The state at T-0, before a single MAVLink packet arrives. A crash here
	 * means a blank screen at the moment the mission starts. */
	const { container } = render(<MissionStatus fleet={EMPTY} online={false} />)
	expect(container).not.toBeEmptyDOMElement()
	// Two of these: survivors found and kits delivered. getAllByText, because
	// getByText throws on more than one match.
	expect(screen.getAllByText("0/10")).toHaveLength(2)
})

test("renders when fleet is null rather than crashing the page", () => {
	const { container } = render(<MissionStatus fleet={null} online={false} />)
	expect(container).toBeEmptyDOMElement()
})
