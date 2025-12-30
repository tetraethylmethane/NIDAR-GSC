// client/src/pages/FlightData/tabs/Main.js
import React, {useEffect, useRef, useState} from "react"
import { Box, Button, Dropdown, Label } from "components/UIElements"
import { Row, Column, Modal, ModalHeader, ModalBody } from "components/Containers"

import styled from "styled-components"
import { ReactComponent as RawUAV } from "icons/uav.svg"
import { ReactComponent as RawUAVbw } from "icons/uav-bw.svg"
import {dark, darkest, darkdark, red} from "theme/Colors"
import {getUrl, httpget, httppost} from "../../../backend"
import VideoFeed from "../../../VideoFeed"
import { useInterval } from "../../../util"
import { darkred } from "../../../theme/Colors"

const Modes = ["Manual", "Auto", "Loiter", "RTL", "Takeoff", "Land", "Circle", "Stabilize"]

const colors = {
	INFO: "#4A90E2",
	IMPORTANT: "#2F6FDB",
	WARNING: "#F59505",
	ERROR: "#E55353",
	CRITICAL: "#B52F9A"
}

const Main = () => {
	const [open, setOpen] = useState(false)

	const [Aarmed, setAarmed] = useState("")
	const [Aorientation, setAorientation] = useState({ "yaw": 0, "pitch": 0, "roll": 0 })
	const [AlatLong, setAlatLong] = useState({ "lat": 0, "lon": 0 })
	const [Aaltitude, setAaltitude] = useState(0)
	const [AaltitudeGlobal, setAaltitudeGlobal] = useState(0)
	const [AebayBattery, setAebayBattery] = useState(16.8)
	const [AflightBattery, setAflightBattery] = useState(50.4)
	const [AgroundSpeed, setAgroundSpeed] = useState(0)
	const [Aairspeed, setAairspeed] = useState(0)
	const [Astatus, setAstatus] = useState("")
	const [Amode, setAmode] = useState("")
	const [Awaypoint, setAwaypoint] = useState([1, 0])
	const [AdistFromHome, setAdistFromHome] = useState(0)
	const [Aconnection, setAconnection] = useState([95, 0, 95])

	const [logs, setLogs] = useState(["Loading logs..."])

	useInterval(400, () => {
		httpget("/uav/stats", response => {
			let data = response.data
			setAarmed(data.result.armed)
			setAorientation({
				"yaw": data.result.quick.orientation.yaw,
				"roll": data.result.quick.orientation.roll,
				"pitch": data.result.quick.orientation.pitch
			})
			setAlatLong({"lat": data.result.quick.lat, "lon": data.result.quick.lon})
			setAaltitude(data.result.quick.altitude)
			setAaltitudeGlobal(data.result.quick.altitude_global)
			setAebayBattery(data.result.quick.battery[0])
			setAflightBattery(data.result.quick.battery[1])
			setAgroundSpeed(data.result.quick.ground_speed)
			setAairspeed(data.result.quick.air_speed)
			setAstatus(data.result.status)
			setAmode(data.result.mode)
			setAwaypoint(data.result.quick.waypoint)
			setAdistFromHome(data.result.quick.dist_from_home)
			setAconnection(data.result.quick.connection)
		})
	})

	useInterval(1000, () => {
		httpget("/rollinglogs", response => {
			setLogs(response.data.result)
		})
	})

	const [waypointNum, setWaypointNum] = useState(1)

	return (
		<MainContainer>
			{/* <Modal open={open} setOpen={setOpen}>
				<ModalHeader>Terminate?</ModalHeader>
				<ModalBody>
					Are you SURE you want to terminate the UAV? If configured properly, this will use AFS_TERMINATE to set:
					<br /><br />
					<ul>
						<li>Throttle Closed</li>
						<li>Full Up Elevator</li>
						<li>Full Right Rudder</li>
						<li>Full Right/Left Aileron</li>
						<li>Full Flaps Down</li>
					</ul>
					<br />
					<b>THE PLANE WILL CRASH!!!</b>
					<br /><br />
					<Button warning={true} color={darkred} style={{ "width": "9rem", height: "2.85rem" }} onClick={() => {
						httppost("/uav/terminate")
						setOpen(false)
					}}>TERMINATE</Button>
				</ModalBody>
			</Modal> */}

			{/* Top Section: Video Feed */}
			<TopSection>
				<VideoFeed />
			</TopSection>

			{/* Compact Data Grid */}
			<CompactDataGrid>
				{/* Row 1: Orientation, Position, Altitude */}
				<DataRow>
					<DataBlock>
						<BlockLabel>ORIENTATION</BlockLabel>
						<MetricsInline>
							<Metric>
								<MLabel>Roll</MLabel>
								<MValue>{Aorientation.roll.toFixed(2)}°</MValue>
							</Metric>
							<Metric>
								<MLabel>Pitch</MLabel>
								<MValue>{Aorientation.pitch.toFixed(2)}°</MValue>
							</Metric>
							<Metric>
								<MLabel>Yaw</MLabel>
								<MValue>{Aorientation.yaw.toFixed(2)}°</MValue>
							</Metric>
						</MetricsInline>
					</DataBlock>

					<DataBlock>
						<BlockLabel>POSITION</BlockLabel>
						<MetricsInline>
							<Metric>
								<MLabel>Lat</MLabel>
								<MValue>{AlatLong.lat.toFixed(7)}°</MValue>
							</Metric>
							<Metric>
								<MLabel>Lon</MLabel>
								<MValue>{AlatLong.lon.toFixed(7)}°</MValue>
							</Metric>
						</MetricsInline>
					</DataBlock>

					<DataBlock>
						<BlockLabel>ALTITUDE</BlockLabel>
						<MetricsInline>
							<Metric>
								<MLabel>AGL</MLabel>
								<MValue>{Aaltitude.toFixed(2)} ft</MValue>
							</Metric>
							<Metric>
								<MLabel>MSL</MLabel>
								<MValue>{AaltitudeGlobal.toFixed(2)} ft</MValue>
							</Metric>
						</MetricsInline>
					</DataBlock>
				</DataRow>

				{/* Row 2: Speed, Battery, Flight Mode */}
				<DataRow>
					<DataBlock>
						<BlockLabel>SPEED</BlockLabel>
						<MetricsInline>
							<Metric>
								<MLabel>Ground</MLabel>
								<MValue>{AgroundSpeed.toFixed(2)} mph</MValue>
								<MSub>{(0.868976 * AgroundSpeed).toFixed(2)} kts</MSub>
							</Metric>
							<Metric>
								<MLabel>Air</MLabel>
								<MValue>{Aairspeed.toFixed(2)} mph</MValue>
								<MSub>{(0.868976 * Aairspeed).toFixed(2)} kts</MSub>
							</Metric>
						</MetricsInline>
					</DataBlock>

					<DataBlock>
						<BlockLabel>BATTERY</BlockLabel>
						<MetricsInline>
							<Metric>
								<MLabel>Flight</MLabel>
								<MValue>{AflightBattery.toFixed(2)} V</MValue>
							</Metric>
							<Metric>
								<MLabel>Ebay</MLabel>
								<MValue>{AebayBattery.toFixed(2)} V</MValue>
							</Metric>
						</MetricsInline>
					</DataBlock>

					<DataBlock>
						<BlockLabel>FLIGHT MODE</BlockLabel>
						<ModeDropdown
							initial={Modes.find(m => m.toUpperCase() === Amode)}
							onChange={i => {
								let m = Modes[i].toUpperCase()
								if (m === "LAND") {
									httppost("/uav/commands/insert", { "command": "LAND", "lat": 0.0, "lon": 0.0, alt: 0.0 })
								} else {
									httppost("/uav/mode/set", { "mode": m })
								}
								setAmode(m)
							}}
						>
							{Modes.map((v, i) => <span key={i} value={i}>{v}</span>)}
						</ModeDropdown>
					</DataBlock>
				</DataRow>

				{/* Row 3: GPS, Waypoint, Controls */}
				<DataRow>
					<DataBlock>
						<BlockLabel>GPS & NAVIGATION</BlockLabel>
						<MetricsInline>
							<Metric>
								<MLabel>Home</MLabel>
								<MValue>{AdistFromHome.toFixed(0)} ft</MValue>
							</Metric>
							<Metric>
								<MLabel>HDOP</MLabel>
								<MValue>{(Aconnection[0] / 100).toFixed(2)} m</MValue>
							</Metric>
							<Metric>
								<MLabel>VDOP</MLabel>
								<MValue>{(Aconnection[1] / 100).toFixed(2)} m</MValue>
							</Metric>
							<Metric>
								<MLabel>Sats</MLabel>
								<MValue>{Aconnection[2].toFixed(0)}</MValue>
							</Metric>
						</MetricsInline>
					</DataBlock>

					<DataBlock>
						<BlockLabel>WAYPOINT</BlockLabel>
						<MetricsInline>
							<Metric>
								<MLabel>Current</MLabel>
								<MValue>{Awaypoint[0] === -1 ? "—" : `#${(Awaypoint[0] + 1).toFixed(0)}`}</MValue>
							</Metric>
							<Metric>
								<MLabel>Distance</MLabel>
								<MValue>{Awaypoint[0] === -1 ? "—" : `${Awaypoint[1].toFixed(2)} ft`}</MValue>
							</Metric>
						</MetricsInline>
					</DataBlock>
				</DataRow>
			</CompactDataGrid>

			{/* Logs Section */}
			<LogsSection>
				<SectionLabel>SYSTEM LOGS</SectionLabel>
				<LogsContainer>
					{logs.map((log, index) => <StyledLog key={index} content={log} index={index} />)}
				</LogsContainer>
			</LogsSection>
		</MainContainer>
	)
}

// Styled Components
const MainContainer = styled.div`
	display: flex;
	flex-direction: column;
	height: calc(100vh - 9.5rem);
	gap: 0.5rem;
	overflow: hidden;
	padding: 0.5rem;
`

const TopSection = styled.div`
	height: 280px;
	flex-shrink: 0;
`
const CompactDataGrid = styled.div`
	display: flex;
	flex-direction: column;
	gap: 0.4rem;
	flex-shrink: 0;
`

const DataRow = styled.div`
	display: grid;
	grid-template-columns: repeat(3, 1fr);
	gap: 0.4rem;
`

const DataBlock = styled.div`
	background: linear-gradient(135deg, rgba(47, 111, 219, 0.03) 0%, rgba(15, 31, 46, 0.02) 100%);
	border: 1px solid rgba(47, 111, 219, 0.12);
	border-radius: 6px;
	padding: 0.4rem 0.6rem;
	display: flex;
	flex-direction: column;
	gap: 0.3rem;
	transition: all 0.2s ease;

	&:hover {
		border-color: rgba(47, 111, 219, 0.25);
		background: linear-gradient(135deg, rgba(47, 111, 219, 0.05) 0%, rgba(15, 31, 46, 0.03) 100%);
	}
`

const BlockLabel = styled.div`
	font-size: 0.65rem;
	font-weight: 600;
	letter-spacing: 0.12em;
	color: #6F879E;
	text-transform: uppercase;
`

const MetricsInline = styled.div`
	display: flex;
	gap: 0.6rem;
	flex-wrap: wrap;
`

const Metric = styled.div`
	display: flex;
	flex-direction: column;
	gap: 0.1rem;
	min-width: 0;
`

const MLabel = styled.div`
	font-size: 0.65rem;
	font-weight: 500;
	color: #8FA6BC;
	letter-spacing: 0.03em;
	text-transform: uppercase;
`

const MValue = styled.div`
	font-size: ${props => props.small ? '0.75rem' : '0.85rem'};
	font-weight: 600;
	color: #2F6FDB;
	font-variant-numeric: tabular-nums;
	letter-spacing: -0.02em;
	white-space: nowrap;
`

const MSub = styled.div`
	font-size: 0.65rem;
	color: #6F879E;
	font-variant-numeric: tabular-nums;
`

const ControlsInline = styled.div`
	display: flex;
	gap: 0.5rem;
	align-items: flex-end;
`

const ControlGroup = styled.div`
	display: flex;
	flex-direction: column;
	gap: 0.25rem;
`

const ControlRow = styled.div`
	display: flex;
	gap: 0.4rem;
	align-items: center;
`

const FlightModeGrid = styled.div`
	display: grid;
	grid-template-columns: 1fr auto;
	gap: 0.75rem;
	align-items: center;
`

const FlightModeLeft = styled.div`
	display: flex;
	flex-direction: column;
	gap: 0.4rem;
`

const ModeDropdown = styled(Dropdown)`
	height: 1.8rem;
	font-size: 0.75rem;
	padding: 0.25rem 0.5rem;
	min-width: 6rem;
	
	button {
		height: 1.8rem;
		font-size: 0.75rem;
		padding: 0.25rem 0.5rem;
	}
`

const ArmStatusContainer = styled.div`
	display: flex;
	flex-direction: column;
	align-items: center;
	gap: 0.3rem;
	justify-content: center;
`

const StatusBadge = styled.div`
	padding: 0.2rem 0.6rem;
	border-radius: 4px;
	font-size: 0.65rem;
	font-weight: 700;
	letter-spacing: 0.05em;
	background: ${props => props.armed ? 
		'linear-gradient(135deg, rgba(47, 191, 113, 0.2), rgba(47, 191, 113, 0.1))' : 
		'linear-gradient(135deg, rgba(143, 166, 188, 0.2), rgba(143, 166, 188, 0.1))'};
	color: ${props => props.armed ? '#2FBF71' : '#8FA6BC'};
	border: 1px solid ${props => props.armed ? 'rgba(47, 191, 113, 0.3)' : 'rgba(143, 166, 188, 0.3)'};
	white-space: nowrap;
`

const UAV = styled(RawUAV)`
	height: 2.5em;
	width: 3.5em;
	cursor: pointer;
	opacity: 0.9;
	transition: all 0.3s ease;

	&:hover {
		opacity: 1;
		transform: scale(1.05);
	}
`

const UAVbw = styled(RawUAVbw)`
	height: 2.5em;
	width: 3.5em;
	cursor: pointer;
	opacity: 0.5;
	transition: all 0.3s ease;

	&:hover {
		opacity: 0.7;
		transform: scale(1.05);
	}
`

const LogsSection = styled.div`
	display: flex;
	flex-direction: column;
	gap: 0.3rem;
	flex: 1;
	min-height: 0;
`

const SectionLabel = styled.div`
	font-size: 0.65rem;
	font-weight: 600;
	letter-spacing: 0.12em;
	color: #6F879E;
	text-transform: uppercase;
`

const LogsContainer = styled.div`
	flex: 1;
	background: linear-gradient(135deg, #0A1628 0%, #12202F 100%);
	border: 1px solid rgba(47, 111, 219, 0.15);
	border-radius: 6px;
	padding: 0.5rem;
	overflow-y: auto;
	overflow-x: hidden;

	&::-webkit-scrollbar {
		width: 6px;
	}

	&::-webkit-scrollbar-track {
		background: rgba(15, 31, 46, 0.3);
		border-radius: 3px;
	}

	&::-webkit-scrollbar-thumb {
		background: rgba(47, 111, 219, 0.3);
		border-radius: 3px;
		transition: background 0.2s;
	}

	&::-webkit-scrollbar-thumb:hover {
		background: rgba(47, 111, 219, 0.5);
	}
`

const StyledLog = ({ content, index }) => {
	let type = content.replace(/\].*/, "").slice(1).trim()
	let date = content.match(/(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d{3}/)
	if (date) {
		date = new Date(date[1])
		let difference = (new Date() - date) / 1000
		content = content.replace(/\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}/, difference.toFixed(0).toString() + "s ago")
	}
	content = content.replace(/\[.*?\]/, "").replace(/\(groundstation\)/, "[gs]").replace(/\(autopilot.*\)/, "[uav]")

	return (
		<StyledLogContainer index={index} color={colors[type] || colors.INFO}>
			<StyledLogText>{content}</StyledLogText>
		</StyledLogContainer>
	)
}

const StyledLogContainer = styled.div`
	border-left: 3px solid ${props => props.color};
	padding-left: 0.5rem;
	margin-bottom: 0.25rem;
	transition: border-color 0.2s;

	&:hover {
		border-left-width: 4px;
	}
`

const StyledLogText = styled.p`
	color: rgba(143, 166, 188, 0.9);
	margin: 0;
	font-size: 0.7rem;
	line-height: 1.3;
	font-family: 'Monaco', 'Consolas', monospace;
`

export default Main