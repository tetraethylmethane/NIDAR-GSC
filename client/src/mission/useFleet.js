/*
 * useFleet — polls the consolidated fleet snapshot.
 *
 * One request, all three drones. Merging happens server-side in
 * mission_backend/fleet.py, which is what actually satisfies the "single
 * unified operator interface" criterion (4D-4, 50 binary points) rather than
 * three panels sitting next to each other.
 *
 * Polling rather than websockets, deliberately: the mission is eight minutes
 * long on a mesh expected to partition, and a dropped poll is self-healing
 * where a dropped socket needs reconnect logic that must itself be correct
 * under exactly the conditions we cannot rehearse.
 */
import { useCallback, useEffect, useRef, useState } from "react"

const EMPTY = {
	vehicles: {},
	regions: {},
	phases: {},
	tasks: {},
	survivors: {},
	deliveries: {},
	progress: {
		found: 0,
		expected: 10,
		delivered: 0,
		elapsed: "0:00",
		bonus_window_s: 900,
		drones_ok: 0,
		drones_total: 3,
		rtk_fixed: 0
	},
	warnings: []
}

const useFleet = (backend, intervalMs = 500) => {
	const [fleet, setFleet] = useState(EMPTY)
	const [online, setOnline] = useState(false)
	const [failures, setFailures] = useState(0)
	const alive = useRef(true)

	const poll = useCallback(async () => {
		try {
			const res = await fetch(`${backend}/api/fleet`)
			if (!res.ok) throw new Error(`HTTP ${res.status}`)
			const data = await res.json()
			if (!alive.current) return
			setFleet(data)
			setOnline(true)
			setFailures(0)
		} catch (e) {
			if (!alive.current) return
			setOnline(false)
			/* Keep the last good snapshot on screen. A blank map during a
			 * scored mission is worse than a stale one, provided staleness is
			 * visible -- which is what `online` drives. */
			setFailures(f => f + 1)
		}
	}, [backend])

	useEffect(() => {
		alive.current = true
		poll()
		const id = setInterval(poll, intervalMs)
		return () => {
			alive.current = false
			clearInterval(id)
		}
	}, [poll, intervalMs])

	return { fleet, online, failures }
}

export { useFleet, EMPTY }
