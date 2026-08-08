/*
 * MissionStatus — consolidated progress and health (rule 8.14 items 1, 7, 8).
 *
 * The single panel a juror should be able to glance at and see the mission
 * state without asking. Everything here comes from one /api/fleet document, so
 * the three aircraft are genuinely merged rather than displayed side by side.
 *
 * The fast-completion bonus (4D-5) is binary at 15 minutes and worth 50 points,
 * so the remaining window is shown as a clock rather than buried in a log.
 */
import styled from "styled-components"
import { DELIVERY_LABEL, droneColor, fixStyle } from "./MissionLayers"

const Panel = styled.div`
	font-family: monospace;
	font-size: 0.82em;
	background: rgba(20, 20, 24, 0.92);
	color: #e6e6e6;
	padding: 0.6em 0.8em;
	display: flex;
	flex-direction: column;
	gap: 0.5em;
`

const Row = styled.div`
	display: flex;
	justify-content: space-between;
	gap: 1em;
`

const Big = styled.span`
	font-size: 1.5em;
	font-weight: bold;
	color: ${props => props.color || "#e6e6e6"};
`

const Warn = styled.div`
	color: #ffb454;
	border-left: 3px solid #ffb454;
	padding-left: 0.5em;
`

const Bad = styled.div`
	color: #ff6b6b;
	border-left: 3px solid #ff6b6b;
	padding-left: 0.5em;
	font-weight: bold;
`

const Dot = styled.span`
	display: inline-block;
	width: 0.65em;
	height: 0.65em;
	border-radius: 50%;
	background: ${props => props.color};
	margin-right: 0.4em;
`

const mmss = s => {
	const t = Math.max(0, Math.floor(s))
	return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, "0")}`
}

const MissionStatus = ({ fleet, online }) => {
	if (!fleet) return null
	const p = fleet.progress || {}
	const bonusLeft = p.bonus_window_s || 0
	const bonusColor = bonusLeft > 300 ? "#6ee7a0" : bonusLeft > 0 ? "#ffb454" : "#ff6b6b"

	return (
		<Panel>
			{!online && <Bad>GCS BACKEND UNREACHABLE — display is stale</Bad>}

			<Row>
				<span>
					survivors
					<br />
					<Big>
						{p.found || 0}/{p.expected || 10}
					</Big>
				</span>
				<span>
					kits delivered
					<br />
					<Big color="#6ee7a0">
						{p.delivered || 0}/{p.expected || 10}
					</Big>
				</span>
				<span>
					elapsed
					<br />
					<Big>{p.elapsed || "0:00"}</Big>
				</span>
				<span>
					bonus window
					<br />
					<Big color={bonusColor}>{mmss(bonusLeft)}</Big>
				</span>
			</Row>

			<Row>
				<span>
					drones {p.drones_ok || 0}/{p.drones_total || 3} healthy
				</span>
				<span>RTK fixed {p.rtk_fixed || 0}/{p.drones_total || 3}</span>
			</Row>

			{/* Per-drone line: 8.14 items 3, 4 and 7 in text form, so the
			  * information survives even if the map fails to render. */}
			{Object.entries(fleet.vehicles || {}).map(([id, v]) => (
				<Row key={id}>
					<span>
						<Dot color={droneColor(Number(id))} />
						D{id} {(fleet.phases || {})[id] || "?"} · {v.mode}
					</span>
					<span>
						{fixStyle(v.gnss_fix).label}
						{v.battery_pct !== null && ` · ${Math.round(v.battery_pct)}%`}
						{v.health !== "OK" && ` · ${v.health}`}
					</span>
				</Row>
			))}

			{/* Delivery ledger — 8.14 item 6. */}
			{Object.keys(fleet.survivors || {}).length > 0 && (
				<div>
					{Object.entries(fleet.survivors).map(([sid, s]) => {
						const d = (fleet.deliveries || {})[sid]
						const state = d ? d.state : "UNASSIGNED"
						return (
							<Row key={sid}>
								<span>
									<Dot color={fixStyle(s.fix).color} />S{sid} {fixStyle(s.fix).label}
								</span>
								<span>{DELIVERY_LABEL[state] || state}</span>
							</Row>
						)
					})}
				</div>
			)}

			{(fleet.warnings || []).map((w, i) => (
				<Warn key={i}>{w}</Warn>
			))}
		</Panel>
	)
}

export default MissionStatus
