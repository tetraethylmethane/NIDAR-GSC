/*
 * AbortPanel — mission abort and emergency recall.
 *
 * Rule 8.19 requires both, and MB §3 lists them among the only four permitted
 * operator actions. In a mission build these are the ONLY controls on screen.
 *
 * THREE THINGS THIS UI HAS TO GET RIGHT
 *
 * 1. It must never show success for a command that was not transmitted. If no
 *    safety radio is attached the backend returns 503 and NO_RADIO, and this
 *    renders a red banner telling the operator to use the safety pilot's
 *    transmitter. A green tick over a dead radio is worse than no button,
 *    because it stops someone reaching for the one thing that would work.
 *
 * 2. It must show WHICH aircraft accepted. On a lossy 868 MHz link "abort
 *    sent" and "abort received" are different claims. Per-drone acknowledgement
 *    is polled and displayed; drones that have not acknowledged stay red.
 *
 * 3. It must not fire on one click. These are the two buttons an operator
 *    reaches for under pressure, and a misclick during a nominal mission ends
 *    it. Two-step arm-then-confirm, with the arm expiring after five seconds.
 */
import { useCallback, useEffect, useRef, useState } from "react"
import styled from "styled-components"
import { getUrl } from "../backend"

const Panel = styled.div`
	font-family: monospace;
	background: #16161a;
	border: 1px solid #333;
	padding: 0.7em;
	display: flex;
	flex-direction: column;
	gap: 0.5em;
`

const Title = styled.div`
	font-size: 0.75em;
	letter-spacing: 0.08em;
	color: #999;
`

const Banner = styled.div`
	background: ${props => (props.bad ? "#4a1414" : "#14331e")};
	color: ${props => (props.bad ? "#ff8a8a" : "#8ff0b0")};
	border-left: 3px solid ${props => (props.bad ? "#d73027" : "#1a9850")};
	padding: 0.4em 0.6em;
	font-size: 0.78em;
	line-height: 1.35;
`

const Buttons = styled.div`
	display: grid;
	grid-template-columns: 1fr 1fr;
	gap: 0.5em;
`

const Big = styled.button`
	font-family: inherit;
	font-weight: bold;
	font-size: ${props => (props.armed ? "1.05em" : "0.95em")};
	padding: 0.8em 0.4em;
	cursor: pointer;
	color: #fff;
	border: 2px solid ${props => (props.armed ? "#fff" : props.accent)};
	background: ${props => (props.armed ? props.accent : "transparent")};
	transition: background 0.1s;
	&:disabled {
		opacity: 0.45;
		cursor: not-allowed;
	}
`

const Drones = styled.div`
	display: flex;
	gap: 0.4em;
	font-size: 0.78em;
`

const Chip = styled.span`
	padding: 0.15em 0.5em;
	border: 1px solid ${props => (props.ok ? "#1a9850" : "#d73027")};
	color: ${props => (props.ok ? "#8ff0b0" : "#ff8a8a")};
`

const ARM_TIMEOUT_MS = 5000

const AbortPanel = ({ pollMs = 700 }) => {
	const [status, setStatus] = useState(null)
	const [armed, setArmed] = useState(null) // "ABORT" | "RECALL" | null
	const [error, setError] = useState(null)
	const armTimer = useRef(null)

	const poll = useCallback(async () => {
		try {
			const res = await fetch(`${getUrl()}/api/safety/status`)
			if (!res.ok) throw new Error(res.status)
			setStatus(await res.json())
		} catch {
			setStatus(null)
		}
	}, [])

	useEffect(() => {
		poll()
		const id = setInterval(poll, pollMs)
		return () => {
			clearInterval(id)
			if (armTimer.current) clearTimeout(armTimer.current)
		}
	}, [poll, pollMs])

	const arm = which => {
		setError(null)
		setArmed(which)
		if (armTimer.current) clearTimeout(armTimer.current)
		/* The arm lapses on its own. An operator who armed by accident and then
		 * looked away must not leave a live trigger on screen. */
		armTimer.current = setTimeout(() => setArmed(null), ARM_TIMEOUT_MS)
	}

	const fire = async which => {
		setArmed(null)
		if (armTimer.current) clearTimeout(armTimer.current)
		try {
			const res = await fetch(`${getUrl()}/api/safety/${which.toLowerCase()}`, {
				method: "POST"
			})
			const body = await res.json()
			setStatus(body)
			if (!res.ok) {
				setError(
					body.state === "NO_RADIO"
						? "NO SAFETY RADIO — nothing was transmitted. Use the safety pilot's transmitter."
						: `Backend returned ${res.status}`
				)
			}
		} catch (e) {
			setError("Could not reach the ground station backend.")
		}
	}

	const click = which => (armed === which ? fire(which) : arm(which))

	const noRadio = status && status.configured === false
	const drones = (status && status.drones) || []
	const acked = (status && status.acknowledged) || []

	return (
		<Panel>
			<Title>SAFETY — ABORT / RECALL</Title>

			{status === null && <Banner bad>Ground station backend unreachable.</Banner>}

			{noRadio && (
				<Banner bad>
					<b>NOT IMPLEMENTED — no safety radio configured.</b>
					<br />
					These buttons record intent in the mission log but transmit nothing.
					Recover the aircraft with the safety pilot&apos;s transmitter.
				</Banner>
			)}

			{error && <Banner bad>{error}</Banner>}

			{status && status.command && !noRadio && (
				<Banner bad={status.state !== "ACKNOWLEDGED"}>
					{status.command} · {status.state}
					{status.elapsed_s != null && ` · ${status.elapsed_s}s`}
					{status.state === "TIMEOUT" &&
						" — not all aircraft acknowledged. Use the transmitter."}
				</Banner>
			)}

			<Buttons>
				<Big
					accent="#b8860b"
					armed={armed === "ABORT"}
					onClick={() => click("ABORT")}
					title="Hold, then sequenced recovery"
				>
					{armed === "ABORT" ? "CONFIRM ABORT" : "ABORT"}
				</Big>
				<Big
					accent="#a3242c"
					armed={armed === "RECALL"}
					onClick={() => click("RECALL")}
					title="Immediate return to launch"
				>
					{armed === "RECALL" ? "CONFIRM RECALL" : "RECALL"}
				</Big>
			</Buttons>

			{armed && <Title>Click again within 5 s to send · {armed}</Title>}

			{drones.length > 0 && (
				<Drones>
					{drones.map(d => (
						<Chip key={d} ok={acked.includes(d)}>
							D{d} {acked.includes(d) ? "ACK" : "—"}
						</Chip>
					))}
				</Drones>
			)}
		</Panel>
	)
}

export default AbortPanel
