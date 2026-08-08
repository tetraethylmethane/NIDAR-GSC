import { useEffect, useRef } from "react"

/*
 * useInterval — a polling interval that can be turned off.
 *
 * Pass `null` (or any non-positive delay) to stop polling entirely. That is
 * what lets a mission build skip the legacy /uav/quick poll: in a mission build
 * app.py does not register the /uav blueprint at all, so polling it would hit a
 * dead path twice a second for the length of the mission. The previous version
 * had no way to express "not now" -- and setInterval(fn, null) coerces the
 * delay to 0, which is a busy loop rather than a stopped one.
 *
 * The callback is held in a ref rather than captured in the effect. With the
 * empty dependency array the old version pinned the FIRST render's closure
 * forever, so a callback reading state saw its initial value for the life of
 * the component while looking perfectly correct on the page. Every existing
 * caller passes a constant delay, so behaviour there is unchanged.
 */
const useInterval = (ms, callback) => {
	const saved = useRef(callback)

	useEffect(() => {
		saved.current = callback
	}, [callback])

	useEffect(() => {
		if (ms === null || ms === undefined || ms <= 0) return undefined
		const tick = setInterval(() => saved.current(), ms)
		return () => clearInterval(tick)
	}, [ms])
}

export { useInterval }
