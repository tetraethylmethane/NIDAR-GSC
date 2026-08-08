import React, { useEffect, useRef, useState } from "react"
import { Row, Modal, ModalBody, ModalHeader } from "components/Containers"
import styled from "styled-components"
import { Box, Button, Dropdown } from "./UIElements"
import { getUrl, setUrl, httpget, httppost } from "../backend"
import { useFleet } from "../mission/useFleet"
import { ReactComponent as RawUAV } from "icons/uav.svg"
import { ReactComponent as RawUAVbw } from "icons/uav-bw.svg"

const Modes = ["Manual", "Auto", "Loiter", "RTL", "Takeoff", "Land", "Circle", "Stabilize"]

const NavContainer = styled.div`
	background: #FFFFFF;
	border-bottom: 2px solid #E2E8F0;
	display: flex;
	align-items: center;
	justify-content: space-between;
	height: 3.5rem;
	padding: 0 1.5rem;
	box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
`

const Logo = styled.h3`
	margin: 0;
	font-size: 0.95rem;
	font-weight: 700;
	letter-spacing: 0.08em;
	color: #2563EB;
	text-transform: uppercase;
`

const NavCenter = styled.div`
	display: flex;
	align-items: center;
	gap: 2rem;
`

const NavLinks = styled.nav`
	display: flex;
	gap: 1.5rem;
	align-items: center;
`

const StyledLink = styled.a`
	text-decoration: none;
	color: #64748B;
	font-size: 0.8rem;
	font-weight: 600;
	letter-spacing: 0.03em;
	text-transform: uppercase;
	transition: all 0.2s ease;
	position: relative;
	padding: 0.5rem 0;

	&:hover {
		color: #2563EB;
	}
`

const FlightModeSection = styled.div`
	display: flex;
	align-items: center;
	gap: 0.75rem;
	padding: 0.35rem 0.75rem;
	background: #F8FAFC;
	border: 1px solid #E2E8F0;
	border-radius: 6px;
`

const ModeInfo = styled.div`
	display: flex;
	align-items: center;
	gap: 0.5rem;
`

const ModeLabel = styled.div`
	font-size: 0.6rem;
	font-weight: 600;
	color: #94A3B8;
	letter-spacing: 0.05em;
	text-transform: uppercase;
`

const ModeDropdown = styled(Dropdown)`
	height: 1.75rem;
	font-size: 0.75rem;
	padding: 0.25rem 0.5rem;
	min-width: 5.5rem;
	background: white;
	border: 1px solid #E2E8F0;
	border-radius: 4px;
	
	button {
		height: 1.75rem;
		font-size: 0.75rem;
		padding: 0.25rem 0.5rem;
		background: white;
		color: #2563EB;
		font-weight: 600;
	}
`

const ArmStatusContainer = styled.div`
	display: flex;
	align-items: center;
	gap: 0.5rem;
	padding-left: 0.75rem;
	border-left: 1px solid #E2E8F0;
`

/*
 * ARMED is not good news, and it was previously styled as though it were:
 * green background, green text, the same visual language as "connected" or
 * "healthy". Armed means the propellers can spin. Every established GCS treats
 * it as a caution, and so should this.
 *
 *   NO DATA   amber   — we do not know, which is the state worth noticing
 *   ARMED     red     — props live
 *   DISARMED  grey    — the quiet, safe, uninteresting case
 */
const StatusBadge = styled.div`
	padding: 0.3rem 0.65rem;
	border-radius: 4px;
	font-size: 0.65rem;
	font-weight: 700;
	letter-spacing: 0.03em;
	background: ${props =>
		props.unknown ? '#FEF3C7' : props.armed ? '#FEE2E2' : '#F1F5F9'};
	color: ${props =>
		props.unknown ? '#B45309' : props.armed ? '#B91C1C' : '#64748B'};
	border: 1px solid ${props =>
		props.unknown ? '#FDE68A' : props.armed ? '#FECACA' : '#E2E8F0'};
	white-space: nowrap;
`

const UAV = styled(RawUAV)`
	height: 2.2em;
	width: 3.2em;
	cursor: pointer;
	opacity: 0.9;
	transition: all 0.3s ease;

	&:hover {
		opacity: 1;
		transform: scale(1.08);
	}
`

const UAVbw = styled(RawUAVbw)`
	height: 2.2em;
	width: 3.2em;
	cursor: pointer;
	opacity: 0.5;
	transition: all 0.3s ease;

	&:hover {
		opacity: 0.7;
		transform: scale(1.08);
	}
`

const SettingsButton = styled.button`
	background: white;
	border: 1px solid #E2E8F0;
	border-radius: 6px;
	padding: 0.45rem 0.9rem;
	cursor: pointer;
	color: #2563EB;
	font-size: 0.75rem;
	font-weight: 600;
	letter-spacing: 0.03em;
	text-transform: uppercase;
	transition: all 0.2s ease;
	display: flex;
	align-items: center;
	gap: 0.4rem;

	&:hover {
		background: #F8FAFC;
		border-color: #CBD5E1;
		box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
	}

	&:active {
		transform: scale(0.98);
	}

	svg {
		width: 14px;
		height: 14px;
	}
`

const SettingsIcon = () => (
	<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
		<circle cx="12" cy="12" r="3"/>
		<path d="M12 1v6m0 6v6M5.64 5.64l4.24 4.24m4.24 4.24l4.24 4.24M1 12h6m6 0h6M5.64 18.36l4.24-4.24m4.24-4.24l4.24-4.24"/>
	</svg>
)

const ModalContent = styled.div`
	display: flex;
	flex-direction: column;
	gap: 1rem;
`

const ModalLabel = styled.div`
	font-size: 0.875rem;
	font-weight: 600;
	color: #6F879E;
	letter-spacing: 0.05em;
	text-transform: uppercase;
	margin-bottom: 0.5rem;
`

const InputRow = styled.div`
	display: flex;
	gap: 0.75rem;
	align-items: flex-end;
`

const ConnectionButton = (props) => {
	const [open, setOpen] = useState(false)
	const boxRef = useRef(null)

	useEffect(() => {
		if (open) {
			boxRef.current?.focus()
		}
	}, [open])

	return (
		<>
			<SettingsButton onClick={() => setOpen(true)}>
				<SettingsIcon />
				Settings
			</SettingsButton>
			<Modal open={open} setOpen={setOpen}>
				<ModalHeader>Backend Connection</ModalHeader>
				<ModalBody>
					<ModalContent>
						<div>
							<ModalLabel>Query URL</ModalLabel>
							<InputRow>
								<Box 
									style={{ flex: 1 }} 
									ref={boxRef} 
									editable={true} 
									content={getUrl()}
								/>
								<Button 
									style={{ height: "2.85rem", minWidth: "8rem" }} 
									onClick={() => {
										setUrl(boxRef.current.value)
										setOpen(false)
									}}
								>
									Set URL
								</Button>
							</InputRow>
						</div>
					</ModalContent>
				</ModalBody>
			</Modal>
		</>
	)
}

/*
 * Arm state for the whole fleet.
 *
 * THE BUG THIS REPLACES. App.js renders <Header /> with no props, so Aarmed
 * defaulted to "" -- and `"".includes("DISARMED")` is false, so the badge read
 * a green ARMED unconditionally. It said ARMED with three disarmed aircraft on
 * the line, and it said ARMED with the backend switched off entirely. The only
 * thing that ever set Aarmed was the Main tab, which a mission build does not
 * render at all.
 *
 * A screenshot found it. No unit test would have: every component involved was
 * behaving exactly as written.
 *
 * Three aircraft cannot be described by one boolean, so this reports the fleet:
 * NO DATA when nothing is arriving, DISARMED when all are down, and "ARMED n/3"
 * when any are live. NO DATA is the important one -- an unknown state must not
 * render as a confident one, in either direction.
 */
const armState = (fleet, online) => {
	const ids = Object.keys(fleet.vehicles || {})
	if (!online || ids.length === 0) {
		return { label: "NO DATA", armed: false, known: false }
	}
	const armed = ids.filter(id => fleet.vehicles[id].armed)
	if (armed.length === 0) {
		return { label: "DISARMED", armed: false, known: true }
	}
	return {
		label: `ARMED ${armed.length}/${ids.length}`,
		armed: true,
		known: true,
	}
}

const Header = ({ Amode = "", setAmode = () => {} }) => {
	/* Mission builds hide every command control. Defaults to TRUE so a failed
	 * fetch produces the safe UI, not the dangerous one. */
	const { fleet, online } = useFleet(getUrl(), 1000)
	const missionMode = fleet.mission_mode !== false
	const arm = armState(fleet, online)

	return (
		<NavContainer>
			<Logo>Drikr NIDAR Ground Station</Logo>
			<NavCenter>
				<NavLinks>
					<StyledLink href="/">Flight Data</StyledLink>
					{/* The Params page reads and WRITES flight-controller
					  * parameters. Rule 8.16 makes a parameter change during the
					  * mission a -50 manual intervention, and unlike a waypoint
					  * it can also render the aircraft unflyable. The page itself
					  * refuses to load in a mission build; hiding the link keeps
					  * anyone from getting that far. */}
					{!missionMode && <StyledLink href="/params">Params</StyledLink>}
				</NavLinks>
					<ArmStatusContainer>
						<StatusBadge armed={arm.armed} unknown={!arm.known}>
							{arm.label}
						</StatusBadge>
						{/* Arm/disarm are rule 8.16 manual interventions at -50 points
						  * each. The server refuses them in a mission build, but a
						  * button that exists at all invites the click, so in mission
						  * mode this is a status indicator and nothing more. */}
						{missionMode ? (
							arm.armed ? <UAV title={arm.label} /> : <UAVbw title={arm.label} />
						) : arm.armed ? (
							<UAV onClick={() => httppost("/uav/disarm")} title="Armed - Click to Disarm (dev build)" />
						) : (
							<UAVbw onClick={() => httppost("/uav/arm")} title="Disarmed - Click to Arm (dev build)" />
						)}
					</ArmStatusContainer>
			</NavCenter>
			<ConnectionButton />
		</NavContainer>
	)
}

export { Header, armState }