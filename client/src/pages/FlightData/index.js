import React, { useState } from "react"

import TabBar from "components/TabBar"
import { httpget } from "backend"

import FlightPlanMap from "components/FlightMap"
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

	useInterval(500, () => {
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
				padding: "0 1rem 0 1rem",
				gridTemplateColumns: "37rem 100fr",
				gap: "1rem",
				width: "100%",
				height: "auto",
				overflowY: "hidden"
			}}
		>
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
			<FlightPlanMap
				display={display}
				getters={getters}
				setters={setters}
			/>
		</div>
	)
}

export default FlightData
