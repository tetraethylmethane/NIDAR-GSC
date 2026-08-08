/*
 * MissionLayers — the map half of rule 8.14.
 *
 * Renders, inside an existing <MapContainer>:
 *   - assigned search region per drone, colour-coded   (8.14 item 4)
 *   - drone positions with fix quality                 (8.14 item 3)
 *   - geotagged survivors with fix quality             (8.14 item 5)
 *   - delivery state per survivor                      (8.14 item 6)
 *
 * WHY THE REGIONS MATTER MOST. Three colour-coded polygons are the *visible
 * proof* that area allocation happened, which is the 50-point multi-drone
 * collaborative execution criterion (4D-3). A juror cannot see CBBA running;
 * they can see that the area was divided three ways and each aircraft stayed
 * in its own piece.
 *
 * WHY FIX QUALITY IS ON THE SURVIVOR MARKER. Delivery is scored from the
 * survivor, so a kit is never more accurate than the tag it was aimed at. A tag
 * taken without RTK is worth ~100 fewer delivery points than one with it. That
 * must be visible while there is still time to re-acquire, not discovered in
 * the post-mission log.
 *
 * READ-ONLY BY CONSTRUCTION. Nothing here dispatches a command. There is no
 * onClick that mutates anything -- see MISSION.md §2.
 */
import { CircleMarker, LayerGroup, LayersControl, Polygon, Tooltip } from "react-leaflet"

/* Distinct at a glance and distinguishable for the most common colour-vision
 * deficiencies -- blue / orange / purple rather than red / green. */
const DRONE_COLOR = {
	1: "#2f7ed8",
	2: "#f28f2b",
	3: "#8b5cf6"
}
const droneColor = id => DRONE_COLOR[id] || "#888888"

/* Fix quality drives colour, because it drives points. */
const FIX_STYLE = {
	RTK_FIXED: { color: "#1a9850", label: "RTK fixed" },
	RTK_FLOAT: { color: "#f6c445", label: "RTK float" },
	DGPS: { color: "#f28f2b", label: "DGPS" },
	"3D": { color: "#d73027", label: "3D only" },
	"2D": { color: "#d73027", label: "2D only" },
	NONE: { color: "#999999", label: "no fix" }
}
const fixStyle = fix => FIX_STYLE[fix] || FIX_STYLE.NONE

const DELIVERY_LABEL = {
	UNASSIGNED: "not assigned",
	ASSIGNED: "assigned",
	EN_ROUTE: "en route",
	RELEASED: "kit released",
	CONFIRMED: "delivered",
	FAILED: "FAILED"
}

/* --------------------------------------------------- assigned search regions */
const Regions = ({ regions }) =>
	Object.entries(regions || {})
		.filter(([, pts]) => pts && pts.length >= 3)
		.map(([id, pts]) => (
			<Polygon
				key={`region-${id}`}
				positions={pts}
				color={droneColor(Number(id))}
				weight={2}
				fillOpacity={0.08}
				interactive={false}
			>
				<Tooltip sticky>Drone {id} search area</Tooltip>
			</Polygon>
		))

/* ------------------------------------------------------------ drone markers */
const Drones = ({ vehicles, phases }) =>
	Object.entries(vehicles || {})
		.filter(([, v]) => v.lat !== null && v.lon !== null)
		.map(([id, v]) => {
			const stale = v.health !== "OK"
			return (
				<CircleMarker
					key={`drone-${id}`}
					center={[v.lat, v.lon]}
					radius={9}
					color={stale ? "#d73027" : droneColor(Number(id))}
					fillColor={droneColor(Number(id))}
					fillOpacity={stale ? 0.25 : 0.85}
					weight={stale ? 3 : 2}
					interactive={false}
				>
					<Tooltip direction="top" offset={[0, -8]}>
						<b>Drone {id}</b> — {(phases || {})[id] || "?"}
						<br />
						{v.mode} {v.armed ? "· armed" : "· disarmed"}
						<br />
						{fixStyle(v.gnss_fix).label} · {v.satellites} sats
						{v.alt_m !== null && <> · {v.alt_m.toFixed(0)} m AGL</>}
						{v.battery_pct !== null && <> · {v.battery_pct.toFixed(0)} %</>}
						{stale && (
							<>
								<br />
								<b>LINK {v.health}</b> ({v.age_s.toFixed(1)} s)
							</>
						)}
					</Tooltip>
				</CircleMarker>
			)
		})

/* --------------------------------------------------------- survivor markers */
const Survivors = ({ survivors, deliveries }) =>
	Object.entries(survivors || {}).map(([sid, s]) => {
		const style = fixStyle(s.fix)
		const delivery = (deliveries || {})[sid]
		const state = delivery ? delivery.state : "UNASSIGNED"
		const done = state === "RELEASED" || state === "CONFIRMED"
		return (
			<LayerGroup key={`survivor-${sid}`}>
				{/* Inner disc: the tag itself, coloured by fix quality. */}
				<CircleMarker
					center={[s.lat, s.lon]}
					radius={7}
					color="#222222"
					weight={1}
					fillColor={style.color}
					fillOpacity={0.95}
					interactive={false}
				>
					<Tooltip direction="top" offset={[0, -6]}>
						<b>Survivor {sid}</b>
						<br />
						tag: {style.label}
						{s.frames > 1 && <> · {s.frames} frames</>}
						{s.confidence > 0 && <> · conf {s.confidence.toFixed(2)}</>}
						<br />
						kit: {DELIVERY_LABEL[state] || state}
						{delivery && delivery.drone_id && <> (drone {delivery.drone_id})</>}
						<br />
						reported by drone {s.reported_by}
					</Tooltip>
				</CircleMarker>

				{/* Outer ring: delivery progress. Solid once a kit is down. */}
				<CircleMarker
					center={[s.lat, s.lon]}
					radius={13}
					color={done ? "#1a9850" : "#666666"}
					weight={done ? 3 : 1}
					dashArray={done ? null : "3 4"}
					fill={false}
					interactive={false}
				/>

				{/* A tag without RTK is a scoring problem while it is still
				 * fixable. Ring it so it cannot be missed on a busy map. */}
				{s.fix !== "RTK_FIXED" && s.fix !== "RTK_FLOAT" && (
					<CircleMarker
						center={[s.lat, s.lon]}
						radius={19}
						color="#d73027"
						weight={2}
						dashArray="2 5"
						fill={false}
						interactive={false}
					/>
				)}
			</LayerGroup>
		)
	})

const MissionLayers = ({ fleet, showRegions = true }) => {
	if (!fleet) return null
	return (
		<>
			<LayersControl.Overlay checked={showRegions} name="Search areas">
				<LayerGroup>
					<Regions regions={fleet.regions} />
				</LayerGroup>
			</LayersControl.Overlay>

			<LayersControl.Overlay checked name="Drones">
				<LayerGroup>
					<Drones vehicles={fleet.vehicles} phases={fleet.phases} />
				</LayerGroup>
			</LayersControl.Overlay>

			<LayersControl.Overlay checked name="Survivors">
				<LayerGroup>
					<Survivors survivors={fleet.survivors} deliveries={fleet.deliveries} />
				</LayerGroup>
			</LayersControl.Overlay>
		</>
	)
}

export default MissionLayers
export { DRONE_COLOR, droneColor, fixStyle, DELIVERY_LABEL }
