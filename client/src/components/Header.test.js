/*
 * The arm badge said ARMED when nothing was armed.
 *
 * App.js renders <Header /> with no props. Aarmed defaulted to "", and
 * `"".includes("DISARMED")` is false, so the badge rendered a green ARMED
 * unconditionally: with three disarmed aircraft on the line, and with the
 * backend switched off entirely. The only thing that ever set Aarmed was the
 * Main tab, which a mission build does not render at all.
 *
 * No unit test would have caught it, because every component was doing exactly
 * what it had been told. It took a screenshot of the running page.
 *
 * These tests are on armState() rather than the rendered Header because the
 * Header pulls in leaflet, styled-components and svg imports; the logic that
 * was wrong is here, and it is the part worth pinning down.
 */
import { armState } from "./Header"
import { EMPTY } from "../mission/useFleet"

const withVehicles = v => ({ ...EMPTY, vehicles: v })

test("no data must not render as a confident state", () => {
	/* The important case. An unknown arm state is not DISARMED and it is
	 * certainly not ARMED. */
	const s = armState(EMPTY, false)
	expect(s.known).toBe(false)
	expect(s.armed).toBe(false)
	expect(s.label).toMatch(/NO DATA/)
})

test("backend unreachable reads as NO DATA even with a stale snapshot", () => {
	const fleet = withVehicles({ 1: { armed: true } })
	expect(armState(fleet, false).label).toMatch(/NO DATA/)
})

test("all three disarmed reads DISARMED — the original bug", () => {
	const fleet = withVehicles({
		1: { armed: false }, 2: { armed: false }, 3: { armed: false },
	})
	const s = armState(fleet, true)
	expect(s.label).toBe("DISARMED")
	expect(s.armed).toBe(false)
})

test("one armed aircraft out of three is reported as such", () => {
	/* Three aircraft cannot be described by one boolean. "ARMED" alone would
	 * hide that two are down, and "DISARMED" would hide that one is live. */
	const fleet = withVehicles({
		1: { armed: true }, 2: { armed: false }, 3: { armed: false },
	})
	const s = armState(fleet, true)
	expect(s.armed).toBe(true)
	expect(s.label).toBe("ARMED 1/3")
})

test("all three armed", () => {
	const fleet = withVehicles({
		1: { armed: true }, 2: { armed: true }, 3: { armed: true },
	})
	expect(armState(fleet, true).label).toBe("ARMED 3/3")
})

test("online but no vehicles yet is still NO DATA", () => {
	expect(armState(withVehicles({}), true).known).toBe(false)
})
