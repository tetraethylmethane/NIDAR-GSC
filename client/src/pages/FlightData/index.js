import React, { useState } from "react"

import TabBar from "components/TabBar"
import { httpget } from "backend"

import FlightPlanMap from "components/FlightMap"
import VideoWall from "components/VideoWall"
import MissionStatus from "../../mission/MissionStatus"
import AbortPanel from "../../mission/AbortPanel"
import { useFleet } from "../../mission/useFleet"
import { getUrl } from "../../backend"
import FlightPlanToolbar from "./tabs/FlightPlan/FlightPlanToolbar"
import Main from "./tabs/Main"
import { useInterval } from "../../util"
import Servo from "./tabs/Servo"

/*
TODO: Home icon
TODO: Waypoint number icon
TODO: Implement marker insertion
TODO: Display current location of plane (use telem, and also need to make plane icon)
TODO: Polyline overlay -> take polyline file (custom file structure) and overlay it onto map (allow for color option in file)
TODO: Commands display in toolbar
TODO: Commands creation in toolbar
TODO: Interactive display list (move around, delete, insert)
TODO: Fix error where waypoint and fence modes display polygon points
T̶O̶D̶O̶:̶ P̶o̶l̶y̶l̶i̶n̶e̶ a̶r̶r̶o̶w̶s̶ s̶h̶o̶w̶i̶n̶g̶ d̶i̶r̶e̶c̶t̶i̶o̶n̶ o̶f̶ w̶a̶y̶p̶o̶i̶n̶t̶s̶
TODO: Display list highlighting (and vice versa)
*/

const FlightData = () => {
	const [flightBoundary, setFlightBoundary] = useState([
	{ lat: 28.422409, lng: 77.526707 },
	{ lat: 28.421060, lng: 77.526310 },
	{ lat: 28.420579, lng: 77.529121 },
	{ lat: 28.419821, lng: 77.533519 },
	{ lat: 28.419353, lng: 77.536255 },
	{ lat: 28.418809, lng: 77.539459 },
	{ lat: 28.418422, lng: 77.541786 },
	{ lat: 28.420411, lng: 77.542362 },
	{ lat: 28.420988, lng: 77.539270 },
	{ lat: 28.423728, lng: 77.537497 },
	{ lat: 28.423739, lng: 77.530822 },
	{ lat: 28.422147, lng: 77.530435 },
	{ lat: 28.421855, lng: 77.529938 },
	{ lat: 28.422409, lng: 77.526707 }
	]);

	const [airdropBoundary, setAirdropBoundary] = useState([
	{ lat: 28.419536, lng: 77.537553 },
	{ lat: 28.419323, lng: 77.538781 },
	{ lat: 28.419520, lng: 77.538839 },
	{ lat: 28.419729, lng: 77.537613 },
	{ lat: 28.419536, lng: 77.537553 }
	]);

	const [uav, setUav] = useState({})
	const [home, setHome] = useState({})
	const [water, setWater] = useState({})

	const [path, setPath] = useState([])
	const [pathSave, setPathSave] = useState([]) // only used for discarding changes
	const [pathSaved, setPathSaved] = useState(true)

	const [placementMode, setPlacementMode] = useState("disabled")
	const [placementType, setPlacementType] = useState("waypoint")
	const [defaultAlt, setDefaultAlt] = useState(250)

	const [currentDistance, setCurrentDistance] = useState(-1)
	const [firstJump, setFirstJump] = useState(-1)
	const [firstPoint, setFirstPoint] = useState(-1)

	const getters = {
		flightBoundary: flightBoundary,
		airdropBoundary: airdropBoundary,
		uav: uav,
		home: home,
		path: path,
		pathSave: pathSave,
		water: water,
		pathSaved: pathSaved,
		placementMode: placementMode,
		placementType: placementType,
		defaultAlt: defaultAlt,
		currentDistance: currentDistance,
		firstJump: firstJump,
		firstPoint: firstPoint
	}

	const setters = {
		flightBoundary: setFlightBoundary,
		airdropBoundary: setAirdropBoundary,
		uav: setUav,
		home: setHome,
		path: setPath,
		pathSave: setPathSave,
		pathSaved: setPathSaved,
		placementMode: setPlacementMode,
		placementType: setPlacementType,
		water: setWater,
		defaultAlt: setDefaultAlt,
		currentDistance: setCurrentDistance,
		firstJump: setFirstJump,
		firstPoint: setFirstPoint
	}

	const display = {
		flightBoundary: ["Mission Boundary", "Mission Boundary"],
		airdropBoundary: ["Air Drop", "Air Drop Boundary"],
		path: ["Waypoint", "Waypoints"],
		home: ["Home", "Home Location"],
		unlim: ["Unlimited Loiter", "Unlimited Loiter"],
		turn: ["Turn Loiter", "Turn Loiter"],
		time: ["Time Loiter", "Time Loiter"],
		jump: ["Jump", "Jump"],
		uav: ["UAV", "UAV Location"],
		water: ["Drop", "Bottle Drop Location"]
	}

	/* One fleet poll for the whole page. The merge happens server-side, which
	 * is what satisfies the "single unified operator interface" criterion
	 * (4D-4, 50 binary points) rather than three panels side by side. */
	const { fleet: missionFleet, online: fleetOnline } = useFleet(getUrl())
	const droneIds = Object.keys(missionFleet.vehicles || {}).map(Number)
	const missionMode = missionFleet.mission_mode !== false

	/* Legacy single-aircraft telemetry. In a mission build this endpoint does
	 * not exist -- app.py does not register the /uav blueprint, because that
	 * import chain pulls in DroneKit, which is single-vehicle by construction
	 * and unimportable on Python >= 3.10. Everything it fed is superseded by
	 * MissionLayers, which draws all three aircraft from the fleet snapshot. */
	useInterval(missionMode ? null : 500, () => {
		httpget("/uav/quick", response => {
			setUav({
				latlng: {
					lat: response.data.result.lat,
					lng: response.data.result.lon
				},
				heading: response.data.result.orientation.yaw
			})
			setWater({
				lat: response.data.result.lat + 0.1 * response.data.result.ground_speed * Math.sin(response.data.result.orientation.yaw * Math.PI / 180),
				lng: response.data.result.lon + 0.1 * response.data.result.ground_speed * Math.cos(response.data.result.orientation.yaw * Math.PI / 180)
			})
			setHome({
				lat: response.data.result.home.lat,
				lng: response.data.result.home.lon
			})
		})
	})

	return (
			<div
			style={{
				display: "grid",
				padding: "0 1rem",
				gridTemplateColumns: "minmax(20rem, 37rem) 1fr",
				gridTemplateRows: "1fr auto",
				gap: "1rem",
				width: "100%",
				overflow: "hidden",
			}}
			>

			<div style={{
				display: "grid",
				gridTemplateRows: "auto auto 1fr",
				gap: "0.6rem",
				minHeight: 0,
				overflow: "hidden",
			}}>
				{/* Rule 8.14 items 1, 6, 7, 8: mission status, delivery state,
				  * comms and system health, consolidated progress. */}
				<MissionStatus fleet={missionFleet} online={fleetOnline} />
				{/* Rule 8.19: mission abort and emergency recall. */}
				<AbortPanel />
				{/* DEV BUILD ONLY.
				  *
				  * Every tab below is a rule 8.16 manual intervention if used
				  * during the Final Mission, at -50 points each: Main sets
				  * flight mode and inserts a LAND command, FlightPlanToolbar
				  * writes missions to the aircraft, Servo drives the payload
				  * release.
				  *
				  * The server already refuses all of it -- the routes are not
				  * even registered in a mission build -- so nothing here can
				  * break a rule. That is not the argument for removing them.
				  * The argument is that a control which silently does nothing
				  * is its own hazard: under pressure someone clicks Write To,
				  * sees no error, and believes the aircraft took it. The same
				  * reasoning removed waypoint insertion from the map.
				  *
				  * In a mission build the left column is mission status and
				  * abort, and nothing else. */}
				{!missionMode && (
					<TabBar>
						<Main />
						<FlightPlanToolbar
							display={display}
							getters={getters}
							setters={setters}
							tabName={"Map"}
						/>
						<Servo />
						{/*<Logs />*/}
					</TabBar>
				)}
			</div>
			<FlightPlanMap
				display={display}
				getters={getters}
				setters={setters}
			/>
			{/* Rule 8.14 item 2: a live camera feed from EACH drone, spanning
			  * the full width so all three are visible at once rather than
			  * switched between. */}
			<div style={{ gridColumn: "1 / -1" }}>
				<VideoWall drones={droneIds.length ? droneIds : [1, 2, 3]} />
			</div>
		</div>
	)
}

export default FlightData
